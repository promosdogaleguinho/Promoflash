import logging
import time
from typing import Any

import httpx

from app.clients.shopee_signature import (
    build_authorization_header,
    build_payload,
    build_signature,
    build_timestamp,
)

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"
DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_LIMIT = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

_SENSITIVE_KEYS = (
    "app_id",
    "appid",
    "secret",
    "app_secret",
    "signature",
    "authorization",
    "credential",
)

PRODUCT_OFFER_FIELDS = """
itemId
productName
commissionRate
commission
appExistRate
appNewRate
webExistRate
webNewRate
price
priceMin
priceMax
priceDiscountRate
sales
imageUrl
shopName
shopId
shopType
productLink
offerLink
periodStartTime
periodEndTime
productCatIds
ratingStar
sellerCommissionRate
shopeeCommissionRate
""".strip()


class ShopeeAffiliateError(Exception):
    """Erro base da Shopee Affiliate API."""


class ShopeeAuthError(ShopeeAffiliateError):
    """Falha de autenticação."""


class ShopeeHttpError(ShopeeAffiliateError):
    """Erro HTTP da API."""


class ShopeeGraphQLError(ShopeeAffiliateError):
    """Erro GraphQL retornado no corpo da resposta."""


class ShopeeTimeoutError(ShopeeAffiliateError):
    """Timeout na chamada HTTP."""


def _truncate_text(value: str, max_length: int = 120) -> str:
    text = value.strip()
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def _sanitize_for_log(value: object, depth: int = 0) -> object:
    if isinstance(value, str):
        return _truncate_text(value)
    if depth > 8:
        if isinstance(value, (dict, list)):
            return "..."
        return value
    if isinstance(value, dict):
        sanitized: dict = {}
        for key, inner in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                sanitized[key] = "***"
            else:
                sanitized[key] = _sanitize_for_log(inner, depth + 1)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_log(item, depth + 1) for item in value[:20]]
    return value


def _escape_graphql_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def build_product_offer_v2_query(
    keyword: str | None,
    page: int,
    limit: int,
) -> str:
    args = [f"page: {int(page)}", f"limit: {int(limit)}"]
    if keyword:
        escaped = _escape_graphql_string(keyword)
        args.append(f'keyword: "{escaped}"')
    args_text = ", ".join(args)
    fields = "\n      ".join(PRODUCT_OFFER_FIELDS.splitlines())
    return (
        "{\n"
        f"  productOfferV2({args_text}) {{\n"
        "    nodes {\n"
        f"      {fields}\n"
        "    }\n"
        "    pageInfo {\n"
        "      page\n"
        "      limit\n"
        "      hasNextPage\n"
        "      scrollId\n"
        "    }\n"
        "  }\n"
        "}"
    )


class ShopeeAffiliateClient:
    def __init__(
        self,
        app_id: str,
        app_secret: str,
        api_url: str = DEFAULT_API_URL,
        timeout: float = DEFAULT_TIMEOUT,
        page_limit: int = DEFAULT_PAGE_LIMIT,
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.app_id = app_id
        self._app_secret = app_secret
        self.api_url = api_url
        self.timeout = timeout
        self.page_limit = page_limit
        self.max_retries = max_retries
        self.metrics = {
            "http_errors": 0,
            "graphql_errors": 0,
            "auth_failures": 0,
            "retries": 0,
            "timeouts": 0,
        }

    def _build_signed_request(self, query: str, now: float | None = None) -> tuple[str, dict[str, str]]:
        timestamp = build_timestamp(now)
        payload = build_payload(query)
        signature = build_signature(
            self.app_id,
            timestamp,
            payload,
            self._app_secret,
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": build_authorization_header(
                self.app_id,
                timestamp,
                signature,
            ),
        }
        return payload, headers

    def execute(self, query: str) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            payload, headers = self._build_signed_request(query)
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        self.api_url,
                        headers=headers,
                        content=payload.encode("utf-8"),
                    )
            except httpx.TimeoutException as exc:
                self.metrics["timeouts"] += 1
                last_error = ShopeeTimeoutError("Timeout na Shopee Affiliate API")
                logger.warning(
                    "Timeout Shopee Affiliate (attempt=%s/%s)",
                    attempt + 1,
                    self.max_retries,
                )
                if attempt + 1 >= self.max_retries:
                    raise last_error from exc
                self.metrics["retries"] += 1
                time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
                continue
            except httpx.HTTPError as exc:
                self.metrics["http_errors"] += 1
                last_error = ShopeeHttpError(f"Erro HTTP Shopee: {exc}")
                logger.error("Erro de rede Shopee Affiliate: %s", type(exc).__name__)
                if attempt + 1 >= self.max_retries:
                    raise last_error from exc
                self.metrics["retries"] += 1
                time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
                continue

            if response.status_code in (401, 403):
                self.metrics["auth_failures"] += 1
                logger.error(
                    "Falha de autenticação Shopee Affiliate (status=%s)",
                    response.status_code,
                )
                raise ShopeeAuthError(
                    f"Autenticação Shopee falhou (HTTP {response.status_code})"
                )

            if response.status_code == 429 or response.status_code >= 500:
                self.metrics["http_errors"] += 1
                last_error = ShopeeHttpError(
                    f"Erro HTTP temporário Shopee: {response.status_code}"
                )
                logger.warning(
                    "HTTP temporário Shopee status=%s attempt=%s/%s",
                    response.status_code,
                    attempt + 1,
                    self.max_retries,
                )
                if attempt + 1 >= self.max_retries:
                    raise last_error
                self.metrics["retries"] += 1
                time.sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
                continue

            if response.status_code >= 400:
                self.metrics["http_errors"] += 1
                logger.error(
                    "Erro HTTP Shopee Affiliate status=%s",
                    response.status_code,
                )
                raise ShopeeHttpError(
                    f"Erro HTTP Shopee: {response.status_code}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                self.metrics["http_errors"] += 1
                raise ShopeeHttpError("Resposta inválida da Shopee Affiliate API") from exc

            if not isinstance(body, dict):
                raise ShopeeHttpError("Resposta inválida da Shopee Affiliate API")

            errors = body.get("errors")
            if errors:
                self.metrics["graphql_errors"] += 1
                message = _extract_graphql_message(errors)
                if _is_auth_graphql_error(message):
                    self.metrics["auth_failures"] += 1
                    raise ShopeeAuthError(f"GraphQL auth: {message}")
                logger.error(
                    "Erro GraphQL Shopee: %s",
                    _sanitize_for_log(errors),
                )
                raise ShopeeGraphQLError(message)

            return body

        if last_error is not None:
            raise last_error
        raise ShopeeAffiliateError("Falha desconhecida na Shopee Affiliate API")

    def product_offer_v2(
        self,
        keyword: str | None = None,
        page: int = 1,
        limit: int | None = None,
    ) -> dict[str, Any]:
        resolved_limit = self.page_limit if limit is None else limit
        query = build_product_offer_v2_query(keyword, page, resolved_limit)
        body = self.execute(query)
        data = body.get("data")
        if data is None:
            raise ShopeeGraphQLError("data=null na resposta productOfferV2")
        if not isinstance(data, dict):
            raise ShopeeGraphQLError("data inválido na resposta productOfferV2")

        offer = data.get("productOfferV2")
        if offer is None:
            return {
                "nodes": [],
                "pageInfo": {
                    "page": page,
                    "limit": resolved_limit,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            }
        if not isinstance(offer, dict):
            raise ShopeeGraphQLError("productOfferV2 inválido")

        nodes = offer.get("nodes")
        if nodes is None:
            nodes = []
        if not isinstance(nodes, list):
            raise ShopeeGraphQLError("nodes inválido em productOfferV2")

        page_info = offer.get("pageInfo") or {}
        if not isinstance(page_info, dict):
            page_info = {}

        return {
            "nodes": [node for node in nodes if isinstance(node, dict)],
            "pageInfo": {
                "page": page_info.get("page", page),
                "limit": page_info.get("limit", resolved_limit),
                "hasNextPage": bool(page_info.get("hasNextPage")),
                "scrollId": page_info.get("scrollId"),
            },
        }


def _extract_graphql_message(errors: object) -> str:
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            message = first.get("message")
            if message:
                return str(message)
        return str(first)
    return str(errors)


def _is_auth_graphql_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in ("auth", "unauthorized", "forbidden", "credential", "signature")
    )
