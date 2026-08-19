import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.coupon_identity import build_coupon_key
from app.models import Coupon, CouponDiscountType

logger = logging.getLogger(__name__)

SOURCE_NAME = "aliexpress"
MAX_DEPTH = 4

_COUPON_CONTAINER_KEYS = (
    "promo_code_info",
    "coupon_info",
    "coupon",
    "coupons",
    "promo_code",
    "coupon_code",
    "code",
    "promotion_code",
    "voucher_code",
)
_CODE_CONTAINER_KEYS = (
    "promo_code",
    "coupon_code",
    "code",
    "promotion_code",
    "voucher_code",
)
_CODE_FIELDS = ("promo_code", "coupon_code", "code", "promotion_code", "voucher_code")
_DESC_FIELDS = (
    "code_value",
    "coupon_desc",
    "promotion_desc",
    "description",
    "discount_desc",
    "coupon_title",
    "title",
)
_VALUE_FIELDS = (
    "discount_value",
    "coupon_value",
    "amount_off",
    "discount_amount",
)
_GENERIC_VALUE_FIELD = "discount"
_PERCENT_FIELDS = ("discount_percentage", "percentage", "percent_off", "discount_rate")
_MIN_FIELDS = (
    "code_mini_spend",
    "minimum_spend",
    "minimum_amount",
    "min_spend",
    "order_min_amount",
    "threshold",
)
_MAX_FIELDS = ("maximum_discount", "max_discount", "discount_cap", "limit_amount")
_START_FIELDS = (
    "code_availabletime_start",
    "start_time",
    "start_at",
    "valid_from",
    "begin_time",
    "promotion_start_time",
)
_END_FIELDS = (
    "code_availabletime_end",
    "end_time",
    "end_at",
    "valid_until",
    "expire_time",
    "promotion_end_time",
)
_URL_FIELDS = (
    "code_promotionurl",
    "coupon_url",
    "promotion_url",
    "promo_url",
    "code_url",
    "landing_page_url",
)
_COUPON_URL_FIELDS = (
    "code_promotionurl",
    "coupon_url",
    "promo_url",
    "code_url",
)
_APP_ONLY_FIELDS = ("app_only", "is_app_only")
_ACTIVATION_FIELDS = ("requires_activation", "requires_rescue", "requires_coupon_rescue")

_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")
_ORDER_DISCOUNT_PATTERN = re.compile(
    r"on\s+order\s+over\s+(brl|usd|r\$)\s*([\d.,]+)\s*,?\s*"
    r"get\s+(brl|usd|r\$)\s*([\d.,]+)\s+off",
    re.IGNORECASE,
)


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip().replace("R$", "").replace("%", "").strip()
    if not text:
        return None
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        text = text.replace(".", "").replace(",", ".")
    elif has_comma:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _first_value(data: dict, fields: tuple[str, ...]) -> object | None:
    for field in fields:
        if field in data and data[field] not in (None, ""):
            return data[field]
    return None


def _parse_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _looks_like_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "sim")


def _has_percentage(data: dict) -> bool:
    return _first_value(data, _PERCENT_FIELDS) is not None


def _has_generic_percentage_discount(data: dict) -> bool:
    raw = data.get(_GENERIC_VALUE_FIELD)
    return raw is not None and "%" in str(raw)


def _is_product_level(data: dict) -> bool:
    return "product_id" in data or "product_title" in data


def _extract_value(data: dict, allow_generic: bool) -> Decimal | None:
    explicit = _first_value(data, _VALUE_FIELDS)
    if explicit is not None:
        return _to_decimal(explicit)
    if allow_generic and not _has_generic_percentage_discount(data):
        return _to_decimal(data.get(_GENERIC_VALUE_FIELD))
    return None


def _extract_percentage(data: dict, allow_generic: bool) -> Decimal | None:
    explicit = _first_value(data, _PERCENT_FIELDS)
    if explicit is not None:
        return _to_decimal(explicit)
    if allow_generic and _has_generic_percentage_discount(data):
        return _to_decimal(data.get(_GENERIC_VALUE_FIELD))
    return None


def _extract_order_discount(
    description: object,
) -> tuple[Decimal | None, Decimal | None]:
    if not description:
        return None, None
    match = _ORDER_DISCOUNT_PATTERN.search(str(description))
    if not match:
        return None, None
    currencies = {match.group(1).lower(), match.group(3).lower()}
    if not currencies.issubset({"brl", "r$"}):
        return None, None
    return _to_decimal(match.group(2)), _to_decimal(match.group(4))


def _resolve_urls(data: dict) -> tuple[str | None, str | None]:
    coupon_url = _first_value(data, _COUPON_URL_FIELDS)
    if coupon_url is None:
        coupon_url = _first_value(data, ("promotion_url", "landing_page_url"))
    affiliate_raw = data.get("affiliate_url") or coupon_url
    return (
        str(coupon_url) if coupon_url else None,
        str(affiliate_raw) if affiliate_raw else None,
    )


def _has_evidence(data: dict, from_coupon_key: bool) -> bool:
    if from_coupon_key:
        return True
    if _first_value(data, _CODE_FIELDS) is not None:
        return True
    if _first_value(data, _COUPON_URL_FIELDS) is not None:
        return True
    has_benefit = (
        _first_value(data, _VALUE_FIELDS) is not None or _has_percentage(data)
    )
    has_scope = (
        _first_value(data, _MIN_FIELDS) is not None
        or _first_value(data, _MAX_FIELDS) is not None
    )
    return has_benefit and has_scope


def _build_coupon(data: dict, from_coupon_key: bool) -> Coupon | None:
    if not isinstance(data, dict):
        return None
    if not _has_evidence(data, from_coupon_key):
        return None

    code_raw = _first_value(data, _CODE_FIELDS)
    code = str(code_raw).strip() if code_raw else None

    allow_generic = from_coupon_key and not _is_product_level(data)
    value = _extract_value(data, allow_generic)
    percentage = _extract_percentage(data, allow_generic)

    if percentage is not None:
        discount_type = CouponDiscountType.PERCENTAGE
    elif value is not None:
        discount_type = CouponDiscountType.FIXED
    else:
        discount_type = CouponDiscountType.OTHER

    desc_raw = _first_value(data, _DESC_FIELDS)
    described_minimum, described_value = _extract_order_discount(desc_raw)
    if value is None and percentage is None and described_value is not None:
        value = described_value
        discount_type = CouponDiscountType.FIXED
    minimum = _to_decimal(_first_value(data, _MIN_FIELDS)) or described_minimum
    maximum = _to_decimal(_first_value(data, _MAX_FIELDS))
    start_at = _parse_datetime(_first_value(data, _START_FIELDS))
    end_at = _parse_datetime(_first_value(data, _END_FIELDS))
    coupon_url, affiliate_url = _resolve_urls(data)

    app_only = any(_looks_like_bool(data.get(field)) for field in _APP_ONLY_FIELDS)
    requires_rescue = any(
        _looks_like_bool(data.get(field)) for field in _ACTIVATION_FIELDS
    )

    if code is None and coupon_url is None and desc_raw is None and value is None and percentage is None:
        return None

    return Coupon(
        source=SOURCE_NAME,
        code=code,
        description=str(desc_raw).strip() if desc_raw else None,
        discount_type=discount_type,
        discount_value=value,
        discount_percentage=percentage,
        minimum_spend=minimum,
        maximum_discount=maximum,
        start_at=start_at,
        end_at=end_at,
        coupon_url=coupon_url,
        affiliate_url=affiliate_url,
        app_only=app_only,
        requires_activation=requires_rescue,
        requires_coupon_rescue=requires_rescue,
        metadata={"raw_coupon": data},
    )


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("{") or stripped.startswith("[")


def _collect_candidates(
    node: object,
    depth: int,
    from_coupon_key: bool,
    out: list[dict],
) -> None:
    if depth > MAX_DEPTH:
        return

    if isinstance(node, dict):
        if from_coupon_key or _first_value(node, _CODE_FIELDS) is not None:
            out.append(node)
        for key, value in node.items():
            child_is_coupon_key = key in _COUPON_CONTAINER_KEYS
            if isinstance(value, str):
                if child_is_coupon_key and _looks_like_json(value):
                    try:
                        parsed = json.loads(value)
                    except (ValueError, TypeError):
                        continue
                    _collect_candidates(parsed, depth + 1, True, out)
                elif key in _CODE_CONTAINER_KEYS:
                    out.append(node)
            elif isinstance(value, (dict, list)):
                _collect_candidates(
                    value, depth + 1, from_coupon_key or child_is_coupon_key, out
                )
    elif isinstance(node, list):
        for element in node:
            _collect_candidates(element, depth + 1, from_coupon_key, out)


def extract_aliexpress_coupons(
    item: dict,
    campaign: dict | None = None,
) -> list[Coupon]:
    if not isinstance(item, dict):
        return []

    candidates: list[dict] = []
    _collect_candidates(item, 0, False, candidates)
    if campaign:
        _collect_candidates(campaign, 0, False, candidates)

    coupons: list[Coupon] = []
    seen_keys: set[str] = set()

    for candidate in candidates:
        has_coupon_container = any(
            key in candidate for key in _COUPON_CONTAINER_KEYS
        )
        from_coupon_key = has_coupon_container or (
            _first_value(candidate, _CODE_FIELDS) is not None
        )
        coupon = _build_coupon(candidate, from_coupon_key)
        if coupon is None:
            continue
        key = build_coupon_key(coupon)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        coupons.append(coupon)

    return coupons
