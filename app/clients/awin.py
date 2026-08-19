import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_API_BASE_URL = "https://api.awin.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 200
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (0.5, 1.0, 2.0)

_SENSITIVE_KEYS = (
    "authorization",
    "token",
    "oauth",
    "bearer",
    "secret",
    "credential",
)


class AwinError(Exception):
    """Erro base da Awin Offers API."""


class AwinAuthError(AwinError):
    """Falha de autenticação."""


class AwinHttpError(AwinError):
    """Erro HTTP da API."""


class AwinTimeoutError(AwinError):
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


class AwinClient:
    def __init__(
        self,
        oauth2_token: str,
        publisher_id: str,
        api_base_url: str = DEFAULT_API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self._oauth2_token = oauth2_token.strip()
        self._publisher_id = str(publisher_id).strip()
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout
        self._page_size = page_size
        self.pages_fetched = 0
        self.retries = 0

    @property
    def promotions_url(self) -> str:
        return (
            f"{self._api_base_url}/publisher/"
            f"{self._publisher_id}/promotions"
        )

    def fetch_promotions(
        self,
        *,
        advertiser_ids: list[int],
        membership: str = "joined",
        region_codes: list[str] | None = None,
        status: str = "active",
        offer_type: str = "all",
        page_size: int | None = None,
    ) -> list[dict[str, Any]]:
        resolved_page_size = page_size or self._page_size
        collected: list[dict[str, Any]] = []
        page = 1
        total: int | None = None
        self.pages_fetched = 0
        self.retries = 0

        while True:
            payload = {
                "filters": {
                    "advertiserIds": advertiser_ids,
                    "membership": membership,
                    "regionCodes": region_codes or ["BR"],
                    "status": status,
                    "type": offer_type,
                },
                "pagination": {
                    "page": page,
                    "pageSize": resolved_page_size,
                },
            }
            response = self._post_promotions(payload)
            self.pages_fetched += 1

            page_items = response.get("data") or []
            if not isinstance(page_items, list):
                raise AwinHttpError("Resposta Awin inválida: data não é lista")

            collected.extend(
                item for item in page_items if isinstance(item, dict)
            )

            pagination = response.get("pagination") or {}
            if isinstance(pagination, dict) and pagination.get("total") is not None:
                try:
                    total = int(pagination["total"])
                except (TypeError, ValueError):
                    total = None

            logger.info(
                "Awin page fetched page=%s size=%s collected=%s total=%s",
                page,
                len(page_items),
                len(collected),
                total,
            )

            if not page_items:
                break
            if total is not None and len(collected) >= total:
                break
            if len(page_items) < resolved_page_size:
                break

            page += 1

        return collected

    def enhanced_feed_url(self, advertiser_id: int | str, locale: str) -> str:
        # Docs curl example uses .jsonl suffix.
        return (
            f"{self._api_base_url}/publishers/{self._publisher_id}/"
            f"awinfeeds/download/{advertiser_id}-retail-{locale}.jsonl"
        )

    def fetch_enhanced_retail_feed(
        self,
        advertiser_id: int | str,
        locale: str = "pt_BR",
        timeout: float = 120.0,
    ) -> bytes:
        """Baixa Enhanced Feed (Google Format) em JSONL via OAuth Bearer.

        Docs: Get Enhanced Feed (Google Format)
        https://help.awin.com/apidocs/retail-publisher-productapidocumentation-1
        """
        url = self.enhanced_feed_url(advertiser_id, locale)
        headers = {"Authorization": f"Bearer {self._oauth2_token}"}
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                    response = client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = AwinTimeoutError(str(exc))
                self.retries += 1
                self._sleep_backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = AwinHttpError(str(exc))
                self.retries += 1
                self._sleep_backoff(attempt)
                continue

            if response.status_code in (401, 403):
                raise AwinAuthError(
                    f"Awin enhanced feed auth failed status={response.status_code}"
                )
            if response.status_code == 404:
                raise AwinHttpError(
                    f"Enhanced feed not found advertiser={advertiser_id} "
                    f"locale={locale}"
                )
            if response.status_code >= 500:
                last_error = AwinHttpError(
                    f"Awin enhanced feed HTTP {response.status_code}"
                )
                self.retries += 1
                self._sleep_backoff(attempt)
                continue
            if response.status_code >= 400:
                raise AwinHttpError(
                    f"Awin enhanced feed HTTP {response.status_code}: "
                    f"{_truncate_text(response.text)}"
                )

            logger.info(
                "Awin enhanced feed downloaded advertiser=%s locale=%s bytes=%s",
                advertiser_id,
                locale,
                len(response.content),
            )
            return response.content

        assert last_error is not None
        raise last_error

    def _post_promotions(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._oauth2_token}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        self.promotions_url,
                        headers=headers,
                        json=payload,
                    )
            except httpx.TimeoutException as exc:
                last_error = AwinTimeoutError(str(exc))
                self.retries += 1
                self._sleep_backoff(attempt)
                continue
            except httpx.HTTPError as exc:
                last_error = AwinHttpError(str(exc))
                self.retries += 1
                self._sleep_backoff(attempt)
                continue

            if response.status_code in (401, 403):
                raise AwinAuthError(
                    f"Awin auth failed status={response.status_code}"
                )

            if response.status_code >= 500:
                last_error = AwinHttpError(
                    f"Awin HTTP {response.status_code}: "
                    f"{_truncate_text(response.text)}"
                )
                self.retries += 1
                self._sleep_backoff(attempt)
                continue

            if response.status_code >= 400:
                raise AwinHttpError(
                    f"Awin HTTP {response.status_code}: "
                    f"{_truncate_text(response.text)}"
                )

            try:
                data = response.json()
            except ValueError as exc:
                raise AwinHttpError(
                    f"Resposta Awin não é JSON: {_truncate_text(response.text)}"
                ) from exc

            if not isinstance(data, dict):
                raise AwinHttpError("Resposta Awin inválida: corpo não é objeto")

            logger.debug(
                "Awin response sanitized=%s",
                _sanitize_for_log(data),
            )
            return data

        assert last_error is not None
        raise last_error

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        if attempt >= len(RETRY_BACKOFF_SECONDS):
            return
        time.sleep(RETRY_BACKOFF_SECONDS[attempt])
