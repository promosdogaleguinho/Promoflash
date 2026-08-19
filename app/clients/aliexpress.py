import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.aliexpress_sku_parser import parse_sku_detail_response
from app.clients.aliexpress_signature import build_signature
from app.sku_models import SkuApiResult, SkuApiStatus

logger = logging.getLogger(__name__)

API_VERSION = "2.0"
RESPONSE_FORMAT = "json"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
API_TIMEZONE = timezone(timedelta(hours=8))
RESP_CODE_SUCCESS = 200
_EMPTY_RESULT_CODES = {405}
_SOFT_FAILURE_CODES = {404, 405}
_EMPTY_RESULT_MESSAGES = ("result is empty",)

_SENSITIVE_KEYS = (
    "app_key",
    "appkey",
    "app_secret",
    "secret",
    "sign",
    "token",
    "access_token",
)
_MAX_DEBUG_BODY_CHARS = 4000

METHOD_PRODUCT_QUERY = "aliexpress.affiliate.product.query"
METHOD_LINK_GENERATE = "aliexpress.affiliate.link.generate"
METHOD_HOT_PRODUCT_QUERY = "aliexpress.affiliate.hotproduct.query"
METHOD_FEATURED_PROMO_GET = "aliexpress.affiliate.featuredpromo.get"
METHOD_FEATURED_PROMO_PRODUCTS_GET = "aliexpress.affiliate.featuredpromo.products.get"
METHOD_PRODUCT_DETAIL_GET = "aliexpress.affiliate.productdetail.get"
METHOD_PRODUCT_SKU_DETAIL_GET = "aliexpress.affiliate.product.sku.detail.get"
METHOD_SMART_MATCH = "aliexpress.affiliate.product.smartmatch"

PRODUCT_QUERY_ROOT_KEY = "aliexpress_affiliate_product_query_response"
HOT_PRODUCT_QUERY_ROOT_KEY = "aliexpress_affiliate_hotproduct_query_response"
FEATURED_PROMO_GET_ROOT_KEY = "aliexpress_affiliate_featuredpromo_get_response"
FEATURED_PROMO_PRODUCTS_ROOT_KEY = (
    "aliexpress_affiliate_featuredpromo_products_get_response"
)
PRODUCT_DETAIL_ROOT_KEY = "aliexpress_affiliate_productdetail_get_response"
SMART_MATCH_ROOT_KEY = "aliexpress_affiliate_product_smartmatch_response"

PRODUCT_FIELDS = (
    "product_id,product_title,product_main_image_url,product_small_image_urls,"
    "product_detail_url,promotion_link,app_sale_price,sale_price,original_price,"
    "target_app_sale_price,target_sale_price,target_original_price,"
    "discount,commission_rate,hot_product_commission_rate,evaluate_rate,"
    "lastest_volume,first_level_category_name,second_level_category_name,"
    "shop_id,shop_url"
)
FEATURED_PRODUCT_FIELDS = f"{PRODUCT_FIELDS},promo_code_info"

_CAMPAIGN_ID_FIELDS = ("promotion_id", "promo_id", "activity_id", "campaign_id")
_CAMPAIGN_NAME_FIELDS = (
    "promotion_name",
    "promo_name",
    "activity_name",
    "campaign_name",
)
_CAMPAIGN_DESC_FIELDS = (
    "promotion_desc",
    "promo_desc",
    "activity_desc",
    "campaign_desc",
    "description",
)
_CAMPAIGN_START_FIELDS = (
    "start_time",
    "promotion_start_time",
    "activity_start_time",
    "start_date",
)
_CAMPAIGN_END_FIELDS = (
    "end_time",
    "promotion_end_time",
    "activity_end_time",
    "end_date",
)


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


def _ensure_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_items_from_container(
    container: object, item_keys: tuple[str, ...]
) -> list[dict]:
    if isinstance(container, list):
        return container
    if isinstance(container, dict):
        for key in item_keys:
            inner = container.get(key)
            if isinstance(inner, list):
                return inner
            if isinstance(inner, dict):
                return [inner]
    return []


def _extract_products_from_container(container: object) -> list[dict]:
    return _extract_items_from_container(container, ("product",))


def _first_field(raw: dict, fields: tuple[str, ...]) -> object | None:
    for field in fields:
        value = raw.get(field)
        if value:
            return value
    return None


def _normalize_campaign(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    return {
        "promotion_id": _first_field(raw, _CAMPAIGN_ID_FIELDS),
        "promotion_name": _first_field(raw, _CAMPAIGN_NAME_FIELDS),
        "promotion_desc": _first_field(raw, _CAMPAIGN_DESC_FIELDS),
        "start_time": _first_field(raw, _CAMPAIGN_START_FIELDS),
        "end_time": _first_field(raw, _CAMPAIGN_END_FIELDS),
        "raw": raw,
    }


class AliExpressClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        endpoint: str,
        sign_method: str = "hmac",
        tracking_id: str | None = None,
        target_currency: str = "BRL",
        target_language: str = "PT",
        ship_to_country: str = "BR",
        debug_responses: bool = False,
    ) -> None:
        self.app_key = app_key
        self._app_secret = app_secret
        self.endpoint = endpoint
        self.sign_method = sign_method
        self.tracking_id = tracking_id
        self.target_currency = target_currency
        self.target_language = target_language
        self.ship_to_country = ship_to_country
        self._debug_responses = debug_responses
        self._sku_detail_cache: dict[
            tuple[str, str, str, str, bool, str | None],
            SkuApiResult,
        ] = {}

    def _build_common_params(self, method: str) -> dict:
        return {
            "app_key": self.app_key,
            "method": method,
            "timestamp": datetime.now(API_TIMEZONE).strftime(TIMESTAMP_FORMAT),
            "format": RESPONSE_FORMAT,
            "v": API_VERSION,
            "sign_method": self.sign_method,
        }

    def _sign(self, params: dict) -> str:
        return build_signature(params, self._app_secret, self.sign_method)

    def call_api(self, method: str, params: dict) -> dict:
        request_params = self._build_common_params(method)
        request_params.update(
            {key: value for key, value in params.items() if value is not None}
        )
        request_params["sign"] = self._sign(request_params)

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.endpoint, data=request_params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Erro HTTP AliExpress (method=%s): %s", method, exc.response.status_code
            )
            return {}
        except httpx.HTTPError as exc:
            logger.error("Erro de conexão AliExpress (method=%s): %s", method, exc)
            return {}
        except ValueError as exc:
            logger.error("Resposta inválida da AliExpress (method=%s): %s", method, exc)
            return {}

    def _build_product_query_params(
        self,
        keywords: str,
        page_no: int,
        page_size: int,
        target_language: str,
        target_currency: str,
        country: str,
    ) -> dict:
        params = {
            "keywords": keywords,
            "page_no": page_no,
            "page_size": page_size,
            "target_currency": target_currency,
            "target_language": target_language,
            "country": country,
            "fields": PRODUCT_FIELDS,
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id
        return params

    def debug_product_query(
        self,
        keywords: str,
        page_no: int = 1,
        page_size: int = 20,
        target_language: str | None = None,
        target_currency: str | None = None,
        country: str | None = None,
    ) -> dict:
        params = self._build_product_query_params(
            keywords,
            page_no,
            page_size,
            target_language or self.target_language,
            target_currency or self.target_currency,
            country or self.ship_to_country,
        )
        return self.call_api(METHOD_PRODUCT_QUERY, params)

    def product_query(
        self,
        keywords: str,
        page_no: int = 1,
        page_size: int = 20,
        target_language: str | None = None,
        target_currency: str | None = None,
        country: str | None = None,
    ) -> list[dict]:
        resolved_language = target_language or self.target_language
        resolved_currency = target_currency or self.target_currency
        resolved_country = country or self.ship_to_country

        params = self._build_product_query_params(
            keywords,
            page_no,
            page_size,
            resolved_language,
            resolved_currency,
            resolved_country,
        )

        response = self.call_api(METHOD_PRODUCT_QUERY, params)
        if not response:
            return []

        if self._has_error(response):
            logger.error(
                "AliExpress retornou erro para product_query (keyword=%s)", keywords
            )
            return []

        return self._normalize_response_products(
            response,
            keyword=keywords,
            country=resolved_country,
            target_language=resolved_language,
            target_currency=resolved_currency,
        )

    def hot_product_query(
        self,
        page_no: int = 1,
        page_size: int = 20,
        category_ids: str | None = None,
        sort: str | None = None,
        min_sale_price: float | None = None,
        max_sale_price: float | None = None,
        target_language: str | None = None,
        target_currency: str | None = None,
        country: str | None = None,
    ) -> list[dict]:
        resolved_language = target_language or self.target_language
        resolved_currency = target_currency or self.target_currency
        resolved_country = country or self.ship_to_country

        params = {
            "page_no": page_no,
            "page_size": page_size,
            "target_language": resolved_language,
            "target_currency": resolved_currency,
            "country": resolved_country,
            "fields": PRODUCT_FIELDS,
            "category_ids": category_ids,
            "sort": sort,
            "min_sale_price": min_sale_price,
            "max_sale_price": max_sale_price,
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        response = self.call_api(METHOD_HOT_PRODUCT_QUERY, params)
        if not response:
            return []
        if self._has_error(response):
            logger.error("AliExpress retornou erro para %s", METHOD_HOT_PRODUCT_QUERY)
            return []

        return self._normalize_response_products(
            response,
            root_key=HOT_PRODUCT_QUERY_ROOT_KEY,
            country=resolved_country,
            target_language=resolved_language,
            target_currency=resolved_currency,
        )

    def featured_promo_get(self) -> list[dict]:
        response = self.call_api(METHOD_FEATURED_PROMO_GET, {})
        if not response:
            return []

        self._maybe_log_full_body(METHOD_FEATURED_PROMO_GET, response)

        if self._has_error(response):
            logger.warning(
                "AliExpress falhou em %s (não bloqueante)",
                METHOD_FEATURED_PROMO_GET,
            )
            return []

        campaigns = self._extract_campaigns(response)
        if not campaigns:
            wrapper = _ensure_dict(response.get(FEATURED_PROMO_GET_ROOT_KEY))
            resp_result = _ensure_dict(wrapper.get("resp_result")) if wrapper else {}
            if self._is_empty_result(
                resp_result.get("resp_code"), resp_result.get("resp_msg")
            ):
                logger.warning(
                    "Featured promo get sem resultados (resp_code=%s: %s)",
                    resp_result.get("resp_code"),
                    resp_result.get("resp_msg"),
                )
            else:
                logger.warning(
                    "Featured promo get sem campanhas. wrapper_keys=%s resp_result_keys=%s",
                    list(wrapper.keys()) if wrapper else list(response.keys()),
                    list(resp_result.keys()),
                )
        return campaigns

    def featured_promo_products_get(
        self,
        promotion_name: str | None = None,
        promotion_id: str | None = None,
        page_no: int = 1,
        page_size: int = 20,
        category_id: str | None = None,
        target_language: str | None = None,
        target_currency: str | None = None,
        country: str | None = None,
    ) -> list[dict]:
        resolved_language = target_language or self.target_language
        resolved_currency = target_currency or self.target_currency
        resolved_country = country or self.ship_to_country

        params = {
            "promotion_name": promotion_name,
            "promotion_id": promotion_id,
            "page_no": page_no,
            "page_size": page_size,
            "category_id": category_id,
            "target_language": resolved_language,
            "target_currency": resolved_currency,
            "country": resolved_country,
            "fields": FEATURED_PRODUCT_FIELDS,
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        response = self.call_api(METHOD_FEATURED_PROMO_PRODUCTS_GET, params)
        if not response:
            return []

        self._maybe_log_full_body(METHOD_FEATURED_PROMO_PRODUCTS_GET, response)

        if self._has_error(response):
            logger.error(
                "AliExpress retornou erro para %s", METHOD_FEATURED_PROMO_PRODUCTS_GET
            )
            return []

        context = {
            "keyword": promotion_name,
            "country": resolved_country,
            "target_language": resolved_language,
            "target_currency": resolved_currency,
        }
        return self._parse_featured_promo_products(response, context)

    def product_detail_get(
        self,
        product_ids: list[str] | str,
        target_language: str | None = None,
        target_currency: str | None = None,
        country: str | None = None,
    ) -> list[dict]:
        resolved_language = target_language or self.target_language
        resolved_currency = target_currency or self.target_currency
        resolved_country = country or self.ship_to_country

        if isinstance(product_ids, str):
            ids_value = product_ids
        else:
            ids_value = ",".join(str(product_id) for product_id in product_ids if product_id)

        if not ids_value:
            return []

        params = {
            "product_ids": ids_value,
            "target_language": resolved_language,
            "target_currency": resolved_currency,
            "country": resolved_country,
            "fields": FEATURED_PRODUCT_FIELDS,
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        response = None
        for attempt in range(2):
            response = self.call_api(METHOD_PRODUCT_DETAIL_GET, params)
            if not response:
                return []
            self._maybe_log_full_body(METHOD_PRODUCT_DETAIL_GET, response)
            if self._is_api_call_limit(response) and attempt == 0:
                logger.warning(
                    "AliExpress rate limit em %s; aguardando 1.2s e tentando de novo",
                    METHOD_PRODUCT_DETAIL_GET,
                )
                time.sleep(1.2)
                continue
            break

        if not response or self._has_error(response):
            logger.warning(
                "AliExpress falhou em %s (não bloqueante)",
                METHOD_PRODUCT_DETAIL_GET,
            )
            return []

        context = {
            "keyword": ids_value[:40],
            "country": resolved_country,
            "target_language": resolved_language,
            "target_currency": resolved_currency,
        }
        return self._parse_product_detail_products(response, context)

    def product_sku_detail_get(
        self,
        product_id: str,
        need_deliver_info: bool = False,
        sku_ids: list[str] | str | None = None,
        ship_to_country: str | None = None,
        target_currency: str | None = None,
        target_language: str | None = None,
    ) -> SkuApiResult:
        resolved_country = ship_to_country or self.ship_to_country
        resolved_currency = target_currency or self.target_currency
        resolved_language = target_language or self.target_language
        normalized_product_id = str(product_id).strip()
        if isinstance(sku_ids, str):
            sku_ids_value = sku_ids.strip() or None
        elif sku_ids:
            normalized_sku_ids = sorted(
                {
                    str(sku_id).strip()
                    for sku_id in sku_ids
                    if str(sku_id).strip()
                }
            )
            sku_ids_value = ",".join(normalized_sku_ids) or None
        else:
            sku_ids_value = None
        cache_key = (
            normalized_product_id,
            resolved_country,
            resolved_currency,
            resolved_language,
            need_deliver_info,
            sku_ids_value,
        )
        cached = self._sku_detail_cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "ship_to_country": resolved_country,
            "product_id": normalized_product_id,
            "target_currency": resolved_currency,
            "target_language": resolved_language,
            "need_deliver_info": "Yes" if need_deliver_info else "No",
            "sku_ids": sku_ids_value,
        }

        response: dict = {}
        for attempt in range(2):
            response = self.call_api(METHOD_PRODUCT_SKU_DETAIL_GET, params)
            if self._is_api_call_limit(response) and attempt == 0:
                logger.warning(
                    "AliExpress rate limit em %s; aguardando 1.2s e tentando de novo",
                    METHOD_PRODUCT_SKU_DETAIL_GET,
                )
                time.sleep(1.2)
                continue
            break

        self._maybe_log_full_body(METHOD_PRODUCT_SKU_DETAIL_GET, response)
        if response:
            result = parse_sku_detail_response(response, normalized_product_id)
        else:
            result = SkuApiResult(
                status=SkuApiStatus.ERROR,
                product_id=normalized_product_id,
                error_code="empty_response",
            )
        if result.status != SkuApiStatus.ERROR:
            self._sku_detail_cache[cache_key] = result

        if result.status == SkuApiStatus.NOT_FOUND:
            logger.info(
                "AliExpress SKU API sem dados para product_id=%s (sub_code=405)",
                normalized_product_id,
            )
        elif result.status == SkuApiStatus.ERROR:
            logger.warning(
                "AliExpress SKU API falhou para product_id=%s code=%s",
                normalized_product_id,
                result.error_code,
            )
        elif result.coverage_may_be_incomplete:
            logger.warning(
                "AliExpress SKU API retornou exatamente 20 SKUs para product_id=%s; "
                "cobertura pode estar incompleta",
                normalized_product_id,
            )
        return result

    def smart_match_products(
        self,
        keywords: str | None = None,
        product_id: str | None = None,
        page_no: int = 1,
        page_size: int = 20,
    ) -> list[dict]:
        # Recurso experimental. A API smartmatch pode exigir parametros extras
        # de contexto (device_id, app, user, site) para recomendacoes reais.
        # Ainda nao usados pelo projeto; adicionar aqui quando forem necessarios.
        params = {
            "keywords": keywords,
            "product_id": product_id,
            "page_no": page_no,
            "page_size": page_size,
            "target_language": self.target_language,
            "target_currency": self.target_currency,
            "country": self.ship_to_country,
            "fields": PRODUCT_FIELDS,
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        response = self.call_api(METHOD_SMART_MATCH, params)
        if not response:
            return []
        if self._has_error(response):
            logger.error("AliExpress retornou erro para %s", METHOD_SMART_MATCH)
            return []

        return self._normalize_response_products(
            response,
            root_key=SMART_MATCH_ROOT_KEY,
        )

    def _extract_result(self, response: dict, root_key: str) -> dict:
        for root in (_ensure_dict(response.get(root_key)), response):
            if not root:
                continue
            resp_result = _ensure_dict(root.get("resp_result"))
            if resp_result:
                if not self._check_resp_code(resp_result):
                    return {}
                result = _ensure_dict(resp_result.get("result"))
                if result:
                    return result
            result = _ensure_dict(root.get("result"))
            if result:
                return result
        return {}

    def _extract_campaigns(self, response: dict) -> list[dict]:
        result = self._extract_result(response, FEATURED_PROMO_GET_ROOT_KEY)
        if not result:
            return []

        container = None
        for key in ("promos", "promotions", "featured_promos"):
            if key in result:
                container = result[key]
                break
        if container is None:
            container = result

        raw_promos = _extract_items_from_container(
            container, ("promo", "promotion", "featured_promo")
        )
        campaigns: list[dict] = []
        for raw in raw_promos:
            campaign = _normalize_campaign(raw)
            if campaign and (campaign["promotion_id"] or campaign["promotion_name"]):
                campaigns.append(campaign)
        return campaigns

    def generate_affiliate_link(self, urls: list[str]) -> list[dict]:
        if not urls:
            return []

        params = {
            "promotion_link_type": 0,
            "source_values": ",".join(urls),
        }
        if self.tracking_id:
            params["tracking_id"] = self.tracking_id

        response = self.call_api(METHOD_LINK_GENERATE, params)
        if not response:
            logger.warning("Nenhuma resposta ao gerar link afiliado AliExpress")
            return []

        if self._has_error(response):
            logger.warning("AliExpress retornou erro ao gerar link afiliado")
            return []

        links = self._extract_promotion_links(response)
        if not links:
            logger.warning(
                "Estrutura inesperada ao gerar link afiliado. Chaves raiz: %s",
                list(response.keys()),
            )
        return links

    @staticmethod
    def _has_error(response: dict) -> bool:
        if "error_response" in response:
            return True
        for value in response.values():
            if isinstance(value, dict) and "error_code" in value:
                return True
        return False

    @staticmethod
    def _is_api_call_limit(response: dict) -> bool:
        error = response.get("error_response")
        if not isinstance(error, dict):
            return False
        code = str(error.get("code") or "").lower()
        message = str(error.get("msg") or "").lower()
        return code == "apicalllimit" or "frequency exceeds" in message

    def _normalize_response_products(
        self,
        response: dict,
        root_key: str = PRODUCT_QUERY_ROOT_KEY,
        keyword: str | None = None,
        country: str | None = None,
        target_language: str | None = None,
        target_currency: str | None = None,
    ) -> list[dict]:
        context = {
            "keyword": keyword,
            "country": country,
            "target_language": target_language,
            "target_currency": target_currency,
        }
        possible_roots = [
            _ensure_dict(response.get(root_key)),
            response,
        ]

        for root in possible_roots:
            if not root:
                continue

            resp_result = _ensure_dict(root.get("resp_result"))
            if resp_result and not self._check_resp_code(resp_result, context):
                return []

            products = self._find_products_in_root(root, resp_result)
            if products:
                return products

        logger.warning(
            "Não foi possível localizar produtos na resposta. Chaves raiz: %s",
            list(response.keys()),
        )
        return []

    @staticmethod
    def _check_resp_code(resp_result: dict, context: dict | None = None) -> bool:
        resp_code = resp_result.get("resp_code")
        resp_msg = resp_result.get("resp_msg")

        if resp_code is not None or resp_msg is not None:
            logger.info("AliExpress resp_code=%s resp_msg=%s", resp_code, resp_msg)

        if resp_code is None:
            return True

        try:
            is_success = int(resp_code) == RESP_CODE_SUCCESS
        except (ValueError, TypeError):
            is_success = False

        if not is_success:
            details = context or {}
            if AliExpressClient._is_soft_failure(resp_code, resp_msg):
                logger.warning(
                    "AliExpress sem resultados (resp_code=%s: %s | keyword=%s "
                    "country=%s)",
                    resp_code,
                    resp_msg,
                    details.get("keyword"),
                    details.get("country"),
                )
            else:
                logger.error(
                    "AliExpress retornou resp_code=%s: %s | keyword=%s country=%s "
                    "target_language=%s target_currency=%s",
                    resp_code,
                    resp_msg,
                    details.get("keyword"),
                    details.get("country"),
                    details.get("target_language"),
                    details.get("target_currency"),
                )
        return is_success

    @staticmethod
    def _is_empty_result(resp_code: object, resp_msg: object) -> bool:
        try:
            if int(resp_code) in _EMPTY_RESULT_CODES:
                return True
        except (ValueError, TypeError):
            pass
        message = str(resp_msg or "").lower()
        return any(fragment in message for fragment in _EMPTY_RESULT_MESSAGES)

    @staticmethod
    def _is_soft_failure(resp_code: object, resp_msg: object) -> bool:
        try:
            if int(resp_code) in _SOFT_FAILURE_CODES:
                return True
        except (ValueError, TypeError):
            pass
        return AliExpressClient._is_empty_result(resp_code, resp_msg)

    def _maybe_log_full_body(self, method: str, response: dict) -> None:
        if not self._debug_responses:
            return
        try:
            body = json.dumps(_sanitize_for_log(response), ensure_ascii=False)
        except (TypeError, ValueError):
            body = str(_sanitize_for_log(response))
        logger.info(
            "[DEBUG] Corpo sanitizado de %s: %s",
            method,
            body[:_MAX_DEBUG_BODY_CHARS],
        )

    def _parse_featured_promo_products(
        self, response: dict, context: dict
    ) -> list[dict]:
        wrapper = _ensure_dict(response.get(FEATURED_PROMO_PRODUCTS_ROOT_KEY))
        roots = [root for root in (wrapper, response) if root]

        for root in roots:
            resp_result = _ensure_dict(root.get("resp_result"))
            if resp_result:
                if not self._check_resp_code(resp_result, context):
                    return []
                result = _ensure_dict(resp_result.get("result"))
            else:
                result = _ensure_dict(root.get("result"))

            products = self._extract_featured_products(result, root)
            if products:
                return products

        self._log_featured_products_diagnostics(response, wrapper)
        return []

    def _parse_product_detail_products(
        self, response: dict, context: dict
    ) -> list[dict]:
        wrapper = _ensure_dict(response.get(PRODUCT_DETAIL_ROOT_KEY))
        roots = [root for root in (wrapper, response) if root]

        for root in roots:
            resp_result = _ensure_dict(root.get("resp_result"))
            if resp_result:
                if not self._check_resp_code(resp_result, context):
                    return []
                result = _ensure_dict(resp_result.get("result"))
            else:
                result = _ensure_dict(root.get("result"))

            products = self._extract_featured_products(result, root)
            if products:
                return products

        logger.warning(
            "Product detail sem produtos. wrapper_keys=%s",
            list(wrapper.keys()) if wrapper else list(response.keys()),
        )
        return []

    @staticmethod
    def _extract_featured_products(result: dict, root: dict) -> list[dict]:
        containers = [
            result.get("products") if isinstance(result, dict) else None,
            root.get("products") if isinstance(root, dict) else None,
        ]
        for container in containers:
            products = _extract_products_from_container(container)
            if products:
                return products
        return []

    @staticmethod
    def _log_featured_products_diagnostics(response: dict, wrapper: dict) -> None:
        resp_result = _ensure_dict(wrapper.get("resp_result")) if wrapper else {}
        result = _ensure_dict(resp_result.get("result")) if resp_result else {}
        products = result.get("products") if isinstance(result, dict) else None

        if isinstance(products, dict):
            products_keys: object = list(products.keys())
        elif products is None:
            products_keys = "ausente"
        else:
            products_keys = type(products).__name__

        logger.warning(
            "Featured products não encontrados. wrapper_keys=%s resp_result_keys=%s "
            "result_keys=%s products=%s",
            list(wrapper.keys()) if wrapper else list(response.keys()),
            list(resp_result.keys()),
            list(result.keys()),
            products_keys,
        )

    def _find_products_in_root(self, root: dict, resp_result: dict) -> list[dict]:
        result = _ensure_dict(resp_result.get("result")) if resp_result else {}
        if not result:
            result = _ensure_dict(root.get("result"))

        containers = [
            result.get("products"),
            root.get("products"),
        ]
        for container in containers:
            products = _extract_products_from_container(container)
            if products:
                return products
        return []

    def _extract_promotion_links(self, response: dict) -> list[dict]:
        link_paths = (
            (
                "aliexpress_affiliate_link_generate_response",
                "resp_result",
                "result",
                "promotion_links",
                "promotion_link",
            ),
            ("resp_result", "result", "promotion_links", "promotion_link"),
            ("result", "promotion_links", "promotion_link"),
            ("promotion_links", "promotion_link"),
        )
        for path in link_paths:
            links = self._follow_path(response, path)
            if isinstance(links, list):
                return links
            if isinstance(links, dict):
                return [links]
        return []

    @staticmethod
    def _follow_path(response: dict, path: tuple[str, ...]):
        current = response
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current
