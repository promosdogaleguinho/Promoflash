import logging

from app.models import Promotion

logger = logging.getLogger(__name__)

_PROMOTION_FIELDS = {
    "affiliate_url",
    "tracking_sub_ids",
    "price",
    "base_price",
    "final_price",
    "old_price",
    "discount_percentage",
    "category",
    "tags",
    "metadata",
    "store",
    "seller_id",
    "seller_name",
    "is_official_store",
    "free_shipping",
    "rating",
    "sales",
    "image_url",
    "coupon_code",
    "coupon_description",
    "payment_method",
    "requires_pix",
    "requires_app",
    "price_conditions",
    "canonical_product_id",
    "expires_at",
    "promotion_tags",
    "is_official_campaign",
    "campaign_name",
    "promotion_score",
}


def _is_valid_item(item: dict) -> bool:
    if not item.get("external_id") or not item.get("source") or not item.get("title"):
        return False
    if not item.get("url") and not item.get("affiliate_url"):
        return False
    return True


def _prepare_item(item: dict) -> dict:
    prepared = dict(item)
    if not prepared.get("url") and prepared.get("affiliate_url"):
        prepared["url"] = prepared["affiliate_url"]
    if prepared.get("final_price") is None and prepared.get("price") is not None:
        prepared["final_price"] = prepared["price"]
    if prepared.get("tags") is None:
        prepared["tags"] = []
    if prepared.get("price_conditions") is None:
        prepared["price_conditions"] = []
    if prepared.get("tracking_sub_ids") is None:
        prepared["tracking_sub_ids"] = []
    if prepared.get("metadata") is None:
        prepared["metadata"] = {}
    if prepared.get("promotion_tags") is None:
        prepared["promotion_tags"] = []
    if prepared.get("is_official_campaign") is None:
        prepared["is_official_campaign"] = False
    return prepared


def normalize(raw_items: list[dict]) -> list[Promotion]:
    promotions: list[Promotion] = []

    for item in raw_items:
        if not _is_valid_item(item):
            logger.warning("Item inválido ignorado: %s", item)
            continue

        prepared = _prepare_item(item)
        kwargs = {key: prepared[key] for key in _PROMOTION_FIELDS if key in prepared}
        promotion = Promotion(
            external_id=prepared["external_id"],
            source=prepared["source"],
            title=prepared["title"],
            url=prepared["url"],
            **kwargs,
        )
        promotions.append(promotion)

    return promotions
