from datetime import datetime, timedelta

from app.coupon_lifecycle import get_timezone
from app.coupon_matcher import attach_coupons_to_promotion
from app.models import Coupon, CouponScopeType, Promotion

TZ = get_timezone("America/Sao_Paulo")


def _promotion(external_id: str = "P1", **kwargs) -> Promotion:
    return Promotion(
        external_id=external_id,
        source="aliexpress",
        title="Produto",
        url="https://example.com",
        **kwargs,
    )


def test_attaches_by_product_scope():
    promotion = _promotion("P1")
    coupon = Coupon(
        source="aliexpress",
        code="A",
        scope_type=CouponScopeType.PRODUCT,
        scope_value="P1",
    )
    attach_coupons_to_promotion(promotion, [coupon])
    assert len(promotion.coupons) == 1
    assert promotion.coupons[0].metadata["attachment_reason"] == "product_scope_match"


def test_attaches_api_product_response():
    promotion = _promotion("P1")
    coupon = Coupon(source="aliexpress", code="A", metadata={"attachment_reason": "api_product_response"})
    attach_coupons_to_promotion(promotion, [coupon])
    assert len(promotion.coupons) == 1


def test_attaches_by_campaign():
    promotion = _promotion("P1", metadata={"campaign_id": "c1"}, is_official_campaign=True)
    coupon = Coupon(
        source="aliexpress",
        code="A",
        campaign_id="c1",
        metadata={"attachment_reason": "api_campaign_response"},
    )
    attach_coupons_to_promotion(promotion, [coupon])
    assert len(promotion.coupons) == 1


def test_attaches_by_manual_binding():
    promotion = _promotion("P1")
    coupon = Coupon(
        source="aliexpress",
        code="A",
        scope_value="P1",
        metadata={"attachment_reason": "manual_product_binding"},
    )
    attach_coupons_to_promotion(promotion, [coupon])
    assert len(promotion.coupons) == 1


def test_does_not_attach_same_platform_only():
    promotion = _promotion("P1")
    coupon = Coupon(source="aliexpress", code="A")
    attach_coupons_to_promotion(promotion, [coupon])
    assert promotion.coupons == []


def test_does_not_attach_other_product():
    promotion = _promotion("P1")
    coupon = Coupon(
        source="aliexpress",
        code="A",
        scope_type=CouponScopeType.PRODUCT,
        scope_value="OTHER",
    )
    attach_coupons_to_promotion(promotion, [coupon])
    assert promotion.coupons == []


def test_does_not_duplicate_coupons():
    promotion = _promotion("P1")
    coupon = Coupon(
        source="aliexpress",
        code="A",
        scope_type=CouponScopeType.PRODUCT,
        scope_value="P1",
    )
    attach_coupons_to_promotion(promotion, [coupon, coupon])
    assert len(promotion.coupons) == 1


def test_records_attachment_reason():
    promotion = _promotion("P1")
    coupon = Coupon(source="aliexpress", code="A", metadata={"attachment_reason": "api_product_response"})
    attach_coupons_to_promotion(promotion, [coupon])
    assert promotion.coupons[0].metadata["attachment_reason"] == "api_product_response"


def test_respects_expired_coupon():
    promotion = _promotion("P1")
    now = datetime(2030, 1, 10, 12, 0, tzinfo=TZ)
    coupon = Coupon(
        source="aliexpress",
        code="A",
        scope_type=CouponScopeType.PRODUCT,
        scope_value="P1",
        end_at=now - timedelta(days=1),
    )
    attach_coupons_to_promotion(promotion, [coupon], now)
    assert promotion.coupons == []


def test_promotion_without_coupons_still_works():
    promotion = _promotion("P1")
    attach_coupons_to_promotion(promotion, [])
    assert promotion.coupons == []
