from datetime import datetime

from app.coupon_identity import build_coupon_key
from app.coupon_lifecycle import is_coupon_expired
from app.models import Coupon, CouponScopeType, Promotion

_EXPLICIT_REASONS = {
    "api_product_response",
    "api_campaign_response",
    "manual_product_binding",
    "manual_category_binding",
    "manual_store_binding",
}


def _normalize(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def _matches_product_scope(coupon: Coupon, promotion: Promotion) -> bool:
    return (
        coupon.scope_type == CouponScopeType.PRODUCT
        and bool(coupon.scope_value)
        and str(coupon.scope_value) == str(promotion.external_id)
    )


def _matches_campaign(coupon: Coupon, promotion: Promotion) -> bool:
    campaign_id = promotion.metadata.get("campaign_id") if promotion.metadata else None
    if campaign_id and (
        str(coupon.campaign_id) == str(campaign_id)
        or str(coupon.scope_value) == str(campaign_id)
    ):
        return True
    if (
        promotion.is_official_campaign
        and coupon.campaign_name
        and coupon.campaign_name == promotion.campaign_name
    ):
        return True
    return False


def _matches_category(coupon: Coupon, promotion: Promotion) -> bool:
    category = promotion.resolved_category or promotion.category
    return bool(
        coupon.scope_value
        and category
        and _normalize(coupon.scope_value) == _normalize(category)
    )


def _matches_store(coupon: Coupon, promotion: Promotion) -> bool:
    store = promotion.seller_id or promotion.store
    return bool(
        coupon.scope_value and store and str(coupon.scope_value) == str(store)
    )


def _binding_reason(coupon: Coupon, promotion: Promotion) -> str | None:
    existing = coupon.metadata.get("attachment_reason")

    if _matches_product_scope(coupon, promotion):
        return existing if existing in _EXPLICIT_REASONS else "product_scope_match"

    if existing == "api_product_response":
        return existing

    if existing == "manual_product_binding" and (
        not coupon.scope_value
        or str(coupon.scope_value) == str(promotion.external_id)
    ):
        return existing

    if existing == "api_campaign_response" and _matches_campaign(coupon, promotion):
        return existing

    if existing == "manual_category_binding" and _matches_category(coupon, promotion):
        return existing

    if existing == "manual_store_binding" and _matches_store(coupon, promotion):
        return existing

    return None


def attach_coupons_to_promotion(
    promotion: Promotion,
    coupons: list[Coupon],
    now: datetime | None = None,
) -> Promotion:
    existing_keys = {build_coupon_key(coupon) for coupon in promotion.coupons}

    for coupon in coupons:
        if now is not None and is_coupon_expired(coupon, now):
            continue

        reason = _binding_reason(coupon, promotion)
        if reason is None:
            continue

        coupon.metadata.setdefault("attachment_reason", reason)

        key = build_coupon_key(coupon)
        if key in existing_keys:
            continue

        existing_keys.add(key)
        promotion.coupons.append(coupon)

    return promotion
