import json
from decimal import Decimal, InvalidOperation
from typing import Any

from app.sku_models import (
    SkuApiResult,
    SkuApiStatus,
    SkuMetrics,
    SkuProperty,
    SkuVariant,
)

SKU_RESPONSE_KEY = "aliexpress_affiliate_product_sku_detail_get_response"
MAX_SKUS_PER_RESPONSE = 20

_VALUE_TRANSLATIONS = {
    "black": "Preto",
    "white": "Branco",
    "blue": "Azul",
    "red": "Vermelho",
    "green": "Verde",
    "gray": "Cinza",
    "grey": "Cinza",
    "gold": "Dourado",
    "silver": "Prata",
    "pink": "Rosa",
    "purple": "Roxo",
}


def _as_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def _parse_int(value: object) -> int | None:
    parsed = _parse_decimal(value)
    if parsed is None:
        return None
    try:
        return int(parsed)
    except (ValueError, OverflowError):
        return None


def _translate_value(value: str) -> str:
    stripped = value.strip()
    return _VALUE_TRANSLATIONS.get(stripped.lower(), stripped)


def _parse_property_container(
    value: object,
    metrics: SkuMetrics | None,
) -> tuple[list[SkuProperty], bool]:
    parsed = value
    invalid = False
    if isinstance(value, str):
        if not value.strip():
            return [], False
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            if metrics is not None:
                metrics.invalid_properties += 1
            return [], True

    if isinstance(parsed, dict):
        entries = [parsed]
    elif isinstance(parsed, list):
        entries = parsed
    elif parsed is None:
        return [], False
    else:
        if metrics is not None:
            metrics.invalid_properties += 1
        return [], True

    properties: list[SkuProperty] = []
    for entry in entries:
        if not isinstance(entry, dict):
            invalid = True
            continue
        for name, raw_value in entry.items():
            key = str(name).strip()
            property_value = str(raw_value).strip() if raw_value is not None else ""
            if not key or not property_value:
                continue
            properties.append(
                SkuProperty(name=key, value=_translate_value(property_value))
            )

    if metrics is not None:
        metrics.parsed_properties += len(properties)
        if invalid:
            metrics.invalid_properties += 1
    return properties, invalid


def _fallback_properties(raw: dict) -> list[SkuProperty]:
    properties: list[SkuProperty] = []
    for key in ("color", "size"):
        value = raw.get(key)
        if value is None or not str(value).strip():
            continue
        properties.append(
            SkuProperty(name=key, value=_translate_value(str(value)))
        )
    return properties


def _extract_payload(response: dict) -> tuple[dict, dict]:
    wrapper = _as_dict(response.get(SKU_RESPONSE_KEY))
    candidates = [wrapper, response]
    envelope: dict = {}
    for candidate in candidates:
        outer_result = _as_dict(candidate.get("result"))
        if outer_result and not envelope:
            envelope = outer_result
        payload = _as_dict(outer_result.get("result"))
        if payload:
            return payload, outer_result
    return {}, envelope


def _extract_raw_skus(payload: dict) -> list[dict]:
    sku_info = payload.get("ae_item_sku_info")
    if isinstance(sku_info, list):
        return [item for item in sku_info if isinstance(item, dict)]
    if not isinstance(sku_info, dict):
        return []

    raw_skus = sku_info.get("traffic_sku_info_list")
    if isinstance(raw_skus, list):
        return [item for item in raw_skus if isinstance(item, dict)]
    if isinstance(raw_skus, dict):
        return [raw_skus]
    return []


def _is_success(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def _parse_sku(raw: dict, metrics: SkuMetrics | None) -> SkuVariant:
    properties, invalid_properties = _parse_property_container(
        raw.get("sku_properties"), metrics
    )
    if not properties:
        properties = _fallback_properties(raw)

    original_price = _parse_decimal(raw.get("price_with_tax"))
    sale_price = _parse_decimal(raw.get("sale_price_with_tax"))
    effective_price = sale_price if sale_price is not None else original_price
    label = " • ".join(property.value for property in properties)

    return SkuVariant(
        sku_id=str(raw.get("sku_id") or "").strip(),
        properties=properties,
        variation_label=label,
        original_price=original_price,
        sale_price=sale_price,
        effective_price=effective_price,
        discount_rate=_parse_decimal(raw.get("discount_rate")),
        currency=str(raw.get("currency")).strip() if raw.get("currency") else None,
        image_url=str(raw.get("sku_image_link")).strip()
        if raw.get("sku_image_link")
        else None,
        affiliate_url=str(raw.get("link")).strip() if raw.get("link") else None,
        shipping_fee=_parse_decimal(raw.get("shipping_fees")),
        delivery_days=_parse_int(raw.get("delivery_days")),
        min_delivery_days=_parse_int(raw.get("min_delivery_days")),
        max_delivery_days=_parse_int(raw.get("max_delivery_days")),
        ship_from_country=str(raw.get("ship_from_country")).strip()
        if raw.get("ship_from_country")
        else None,
        rejection_reason="sku_properties_invalid" if invalid_properties else None,
        raw=dict(raw),
    )


def parse_sku_detail_response(
    response: dict,
    product_id: str,
    metrics: SkuMetrics | None = None,
) -> SkuApiResult:
    error = _as_dict(response.get("error_response"))
    if error:
        sub_code = str(error.get("sub_code") or "")
        if sub_code == "405":
            return SkuApiResult(
                status=SkuApiStatus.NOT_FOUND,
                product_id=product_id,
                error_code=sub_code,
                raw=response,
            )
        return SkuApiResult(
            status=SkuApiStatus.ERROR,
            product_id=product_id,
            error_code=sub_code or str(error.get("code") or ""),
            error_message=str(error.get("msg") or error.get("message") or "") or None,
            raw=response,
        )

    payload, outer_result = _extract_payload(response)
    success = outer_result.get("success")
    if success is not None and not _is_success(success):
        return SkuApiResult(
            status=SkuApiStatus.ERROR,
            product_id=product_id,
            error_code=str(outer_result.get("code") or ""),
            raw=response,
        )
    code = outer_result.get("code")
    if code is not None and str(code) != "200":
        return SkuApiResult(
            status=SkuApiStatus.ERROR,
            product_id=product_id,
            error_code=str(code),
            raw=response,
        )

    if not payload:
        return SkuApiResult(
            status=SkuApiStatus.EMPTY,
            product_id=product_id,
            raw=response,
        )

    raw_skus = _extract_raw_skus(payload)
    skus = [_parse_sku(raw, metrics) for raw in raw_skus]
    return SkuApiResult(
        status=SkuApiStatus.SUCCESS if skus else SkuApiStatus.EMPTY,
        product_id=product_id,
        skus=skus,
        item_info=_as_dict(payload.get("ae_item_info")),
        coverage_may_be_incomplete=len(skus) == MAX_SKUS_PER_RESPONSE,
        raw=response,
    )
