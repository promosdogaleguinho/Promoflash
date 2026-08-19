import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

logger = logging.getLogger(__name__)

SOURCE_NAME = "shopee"
STORE_NAME = "Shopee"
PERIOD_OPEN_ENDED_SENTINEL = 32503651199

SHOP_TYPE_LABELS = {
    1: "shopee_mall",
    2: "star_shop",
    4: "star_plus_shop",
}


def to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("%", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def to_float(value: object) -> float | None:
    decimal_value = to_decimal(value)
    if decimal_value is None:
        return None
    return float(decimal_value)


def to_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(Decimal(text))
    except (InvalidOperation, ValueError):
        return None


def _parse_shop_types(raw: object) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, int):
        return [raw]
    if not isinstance(raw, list):
        return []
    types: list[int] = []
    for item in raw:
        parsed = to_int(item)
        if parsed is not None:
            types.append(parsed)
    return types


def derive_shop_tier(shop_types: list[int]) -> str:
    if 1 in shop_types:
        return "mall"
    if 4 in shop_types:
        return "star_plus"
    if 2 in shop_types:
        return "star"
    return "standard"


def _normalize_category_ids(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return []
    result: list[int] = []
    for item in raw:
        parsed = to_int(item)
        if parsed is None:
            continue
        result.append(parsed)
    return result


def _classification_category_ids(category_ids: list[int]) -> list[int]:
    return [category_id for category_id in category_ids if category_id != 0]


def _parse_unix_timestamp(value: object) -> int | None:
    parsed = to_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _datetime_from_unix(value: int | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def evaluate_period(
    period_start_raw: object,
    period_end_raw: object,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    start_unix = _parse_unix_timestamp(period_start_raw)
    end_unix = _parse_unix_timestamp(period_end_raw)

    period_open_ended = end_unix == PERIOD_OPEN_ENDED_SENTINEL
    if period_open_ended:
        end_unix = None

    period_start_at = _datetime_from_unix(start_unix)
    period_end_at = _datetime_from_unix(end_unix)

    not_started = bool(period_start_at and period_start_at > current)
    expired = bool(period_end_at and period_end_at < current)

    return {
        "period_start_at": period_start_at.isoformat() if period_start_at else None,
        "period_end_at": period_end_at.isoformat() if period_end_at else None,
        "period_open_ended": period_open_ended,
        "not_started": not_started,
        "expired": expired,
        "is_valid": not not_started and not expired,
    }


def resolve_main_price(
    price: Decimal | None,
    price_min: Decimal | None,
) -> Decimal | None:
    if price is not None and price > 0:
        return price
    if price_min is not None and price_min > 0:
        return price_min
    return None


def normalize_discount_percentage(rate: Decimal) -> Decimal:
    if rate <= 0:
        return rate
    if rate <= 1:
        return rate * Decimal("100")
    return rate


def estimate_original_price(
    price: Decimal,
    discount_rate: Decimal,
) -> Decimal | None:
    percent = normalize_discount_percentage(discount_rate)
    if percent <= 0 or percent >= 100:
        return None
    fraction = percent / Decimal("100")
    original = price / (Decimal("1") - fraction)
    return original.quantize(Decimal("0.01"))


def map_shopee_product(
    node: dict,
    keyword: str | None = None,
    now: datetime | None = None,
) -> dict | None:
    if not isinstance(node, dict):
        return None

    item_id = to_int(node.get("itemId"))
    shop_id = to_int(node.get("shopId"))
    title = str(node.get("productName") or "").strip()
    offer_link = str(node.get("offerLink") or "").strip() or None
    product_link = str(node.get("productLink") or "").strip() or None

    if item_id is None or shop_id is None:
        logger.info("Shopee node rejeitado: identidade inválida")
        return None
    if not title:
        logger.info("Shopee node rejeitado: título ausente (item_id=%s)", item_id)
        return None
    if not offer_link:
        logger.info(
            "Shopee node rejeitado: offerLink ausente (shop_id=%s item_id=%s)",
            shop_id,
            item_id,
        )
        return None

    price = to_decimal(node.get("price"))
    price_min = to_decimal(node.get("priceMin"))
    price_max = to_decimal(node.get("priceMax"))
    main_price = resolve_main_price(price, price_min)
    if main_price is None:
        logger.info(
            "Shopee node rejeitado: sem preço válido (shop_id=%s item_id=%s)",
            shop_id,
            item_id,
        )
        return None

    period = evaluate_period(
        node.get("periodStartTime"),
        node.get("periodEndTime"),
        now=now,
    )
    if not period["is_valid"]:
        reason = "ainda não iniciado" if period["not_started"] else "expirado"
        logger.info(
            "Shopee node rejeitado: vigência %s (shop_id=%s item_id=%s)",
            reason,
            shop_id,
            item_id,
        )
        return None

    shop_types = _parse_shop_types(node.get("shopType"))
    shop_tier = derive_shop_tier(shop_types)
    category_ids = _normalize_category_ids(node.get("productCatIds"))
    classification_ids = _classification_category_ids(category_ids)
    discount = to_decimal(node.get("priceDiscountRate"))
    if discount is None or discount <= 0:
        logger.info(
            "Shopee node rejeitado: sem desconto (shop_id=%s item_id=%s rate=%s)",
            shop_id,
            item_id,
            node.get("priceDiscountRate"),
        )
        return None

    discount_percent = normalize_discount_percentage(discount)
    if discount_percent <= 0:
        logger.info(
            "Shopee node rejeitado: desconto inválido (shop_id=%s item_id=%s rate=%s)",
            shop_id,
            item_id,
            node.get("priceDiscountRate"),
        )
        return None

    old_price = estimate_original_price(main_price, discount)
    rating = to_decimal(node.get("ratingStar"))
    external_id = f"{shop_id}:{item_id}"
    has_price_range = (
        price_min is not None
        and price_max is not None
        and price_min != price_max
    )

    main_price_float = float(main_price)
    discount_float = float(discount_percent)
    old_price_float = float(old_price) if old_price is not None else None
    rating_float = float(rating) if rating is not None else None

    metadata = {
        "item_id": str(item_id),
        "shop_id": str(shop_id),
        "product_link": product_link,
        "offer_link": offer_link,
        "price_min": str(price_min) if price_min is not None else None,
        "price_max": str(price_max) if price_max is not None else None,
        "has_price_range": has_price_range,
        "original_price_estimated": old_price is not None,
        "commission": (
            str(to_decimal(node.get("commission")))
            if to_decimal(node.get("commission")) is not None
            else None
        ),
        "commission_rate": (
            str(to_decimal(node.get("commissionRate")))
            if to_decimal(node.get("commissionRate")) is not None
            else None
        ),
        "seller_commission_rate": (
            str(to_decimal(node.get("sellerCommissionRate")))
            if to_decimal(node.get("sellerCommissionRate")) is not None
            else None
        ),
        "shopee_commission_rate": (
            str(to_decimal(node.get("shopeeCommissionRate")))
            if to_decimal(node.get("shopeeCommissionRate")) is not None
            else None
        ),
        "app_exist_rate": (
            str(to_decimal(node.get("appExistRate")))
            if to_decimal(node.get("appExistRate")) is not None
            else None
        ),
        "app_new_rate": (
            str(to_decimal(node.get("appNewRate")))
            if to_decimal(node.get("appNewRate")) is not None
            else None
        ),
        "web_exist_rate": (
            str(to_decimal(node.get("webExistRate")))
            if to_decimal(node.get("webExistRate")) is not None
            else None
        ),
        "web_new_rate": (
            str(to_decimal(node.get("webNewRate")))
            if to_decimal(node.get("webNewRate")) is not None
            else None
        ),
        "shop_types": shop_types,
        "shop_type_labels": [
            SHOP_TYPE_LABELS[shop_type]
            for shop_type in shop_types
            if shop_type in SHOP_TYPE_LABELS
        ],
        "shop_tier": shop_tier,
        "period_start_at": period["period_start_at"],
        "period_end_at": period["period_end_at"],
        "period_open_ended": period["period_open_ended"],
        "product_cat_ids": category_ids,
        "classification_cat_ids": classification_ids,
        "keyword": keyword,
        "collector_type": "product_offer_v2",
        "source_platform": SOURCE_NAME,
        "raw": node,
    }

    return {
        "source": SOURCE_NAME,
        "external_id": external_id,
        "canonical_product_id": external_id,
        "title": title,
        "price": main_price_float,
        "final_price": main_price_float,
        "old_price": old_price_float,
        "discount_percentage": discount_float,
        "image_url": str(node.get("imageUrl") or "").strip() or None,
        "url": offer_link,
        "affiliate_url": offer_link,
        "seller_id": str(shop_id),
        "seller_name": str(node.get("shopName") or "").strip() or None,
        "store": STORE_NAME,
        "rating": rating_float,
        "sales": to_int(node.get("sales")),
        "category_ids": classification_ids,
        "tags": [],
        "promotion_tags": [],
        "is_official_store": shop_tier == "mall",
        "metadata": metadata,
    }
