import logging

from app.campaigns import get_campaign_display_name

logger = logging.getLogger(__name__)

SOURCE_NAME = "aliexpress"
STORE_NAME = "AliExpress"

COLLECTOR_PRODUCT_SEARCH = "product_search"
COLLECTOR_HOT_PRODUCTS = "hot_products"
COLLECTOR_FEATURED_PROMOTIONS = "featured_promotions"

_FINAL_PRICE_FIELDS = (
    "target_app_sale_price",
    "target_sale_price",
    "app_sale_price",
    "sale_price",
)
_OLD_PRICE_FIELDS = ("target_original_price", "original_price")
_PRICE_METADATA_FIELDS = (
    "target_app_sale_price",
    "target_sale_price",
    "app_sale_price",
    "sale_price",
    "target_original_price",
    "original_price",
    "discount",
)
_CAMPAIGN_FIELDS = (
    "campaign_name",
    "promotion_name",
    "promo_name",
    "activity_name",
    "event_name",
    "featured_promo_name",
)


def _clean_number_text(text: str) -> str:
    has_dot = "." in text
    has_comma = "," in text

    if has_dot and has_comma:
        return text.replace(".", "").replace(",", ".")
    if has_comma:
        return text.replace(",", ".")
    return text


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(_clean_number_text(text))
    except ValueError:
        return None


def to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_discount(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "").replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_evaluate_rate(value: object) -> float | None:
    percent = parse_discount(value)
    if percent is None:
        return None
    return round(percent / 20, 2)


def _pick_first_price(
    item: dict, fields: tuple[str, ...]
) -> tuple[float | None, str | None]:
    for field in fields:
        price = to_float(item.get(field))
        if price is not None:
            return price, field
    return None, None


def _resolve_old_price(
    item: dict, final_price: float | None
) -> tuple[float | None, str | None]:
    old_price, source = _pick_first_price(item, _OLD_PRICE_FIELDS)
    if old_price is None or final_price is None:
        return old_price, source
    if old_price <= final_price:
        return None, None
    return old_price, source


def _detect_campaign(raw: dict) -> str | None:
    for field in _CAMPAIGN_FIELDS:
        value = raw.get(field)
        if value:
            return str(value).strip()
    return None


def _extract_image(item: dict) -> str | None:
    main_image = item.get("product_main_image_url")
    if main_image:
        return main_image

    small_images = item.get("product_small_image_urls")
    candidates: list = []
    if isinstance(small_images, dict):
        maybe = small_images.get("string")
        if isinstance(maybe, list):
            candidates = maybe
    elif isinstance(small_images, list):
        candidates = small_images

    for url in candidates:
        if isinstance(url, str) and url.strip():
            return url

    fallback = item.get("image_url")
    return fallback or None


def _merge_tags(base: list[str], extra: list[str] | None) -> list[str]:
    merged: list[str] = []
    for tag in list(base) + list(extra or []):
        if tag and tag not in merged:
            merged.append(tag)
    return merged


def map_aliexpress_product(
    item: dict,
    keyword: str | None = None,
    collector_type: str = COLLECTOR_PRODUCT_SEARCH,
    is_official_campaign: bool = False,
    campaign_name: str | None = None,
    extra_tags: list[str] | None = None,
    extra_metadata: dict | None = None,
) -> dict | None:
    if not isinstance(item, dict):
        return None

    product_id = item.get("product_id")
    title = item.get("product_title")
    detail_url = item.get("product_detail_url")
    promotion_link = item.get("promotion_link")

    affiliate_url = promotion_link or detail_url
    url = detail_url or promotion_link

    final_price, price_source = _pick_first_price(item, _FINAL_PRICE_FIELDS)

    if not product_id:
        return None
    if not title:
        return None
    if final_price is None:
        return None
    if not affiliate_url and not url:
        return None

    old_price, old_price_source = _resolve_old_price(item, final_price)

    resolved_campaign = campaign_name
    resolved_official = is_official_campaign
    if not resolved_campaign and not resolved_official:
        detected = _detect_campaign(item)
        if detected:
            resolved_campaign = detected
            resolved_official = True
    if resolved_campaign:
        resolved_campaign = get_campaign_display_name(resolved_campaign)

    first_category = item.get("first_level_category_name")
    second_category = item.get("second_level_category_name")
    tags = [second_category] if second_category else []
    shop_id = item.get("shop_id")

    promotion_tags = _merge_tags([], extra_tags)
    if resolved_campaign:
        promotion_tags = _merge_tags(promotion_tags, [resolved_campaign])

    metadata = {
        "raw": item,
        "source_platform": SOURCE_NAME,
        "collector_type": collector_type,
        "keyword": keyword,
        "price_fields": {field: item.get(field) for field in _PRICE_METADATA_FIELDS},
        "price_source": price_source,
        "old_price_source": old_price_source,
        "commission_rate": item.get("commission_rate"),
        "hot_product_commission_rate": item.get("hot_product_commission_rate"),
        "shop_url": item.get("shop_url"),
        "evaluate_rate": item.get("evaluate_rate"),
        "first_level_category_name": first_category,
        "second_level_category_name": second_category,
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return {
        "external_id": str(product_id),
        "source": SOURCE_NAME,
        "title": title,
        "url": url,
        "affiliate_url": affiliate_url,
        "price": final_price,
        "final_price": final_price,
        "old_price": old_price,
        "discount_percentage": parse_discount(item.get("discount")),
        "category": first_category,
        "tags": tags,
        "metadata": metadata,
        "store": STORE_NAME,
        "seller_id": str(shop_id) if shop_id is not None else None,
        "seller_name": None,
        "rating": parse_evaluate_rate(item.get("evaluate_rate")),
        "sales": to_int(item.get("lastest_volume")),
        "image_url": _extract_image(item),
        "promotion_tags": promotion_tags,
        "is_official_campaign": resolved_official,
        "campaign_name": resolved_campaign,
    }
