from datetime import datetime, timedelta
from decimal import Decimal

from app.coupon_lifecycle import get_timezone
from app.coupon_repost_policy import (
    build_campaign_snapshot,
    build_content_fingerprint,
    should_send_campaign,
)
from app.models import Coupon, CouponCampaign, CouponDiscountType

TZ = get_timezone("America/Sao_Paulo")
NOW = datetime(2030, 1, 12, 12, 0, tzinfo=TZ)


def _fixed_coupon(code: str, value: str) -> Coupon:
    return Coupon(
        source="aliexpress",
        code=code,
        discount_type=CouponDiscountType.FIXED,
        discount_value=Decimal(value),
    )


def _campaign(coupons, **overrides) -> CouponCampaign:
    data = {"source": "aliexpress", "campaign_id": "c1", "title": "Evento", "coupons": coupons}
    data.update(overrides)
    return CouponCampaign(**data)


def test_blocks_duplicate_within_window():
    campaign = _campaign([_fixed_coupon("EX01", "12")])
    snapshot = build_campaign_snapshot(campaign, ["chat1"], NOW)
    assert should_send_campaign(campaign, [snapshot], NOW, 12) is False


def test_allows_new_coupon():
    v1 = _campaign([_fixed_coupon("EX01", "12")])
    snapshot = build_campaign_snapshot(v1, ["chat1"], NOW)
    v2 = _campaign([_fixed_coupon("EX01", "12"), _fixed_coupon("EX02", "28")])
    assert should_send_campaign(v2, [snapshot], NOW, 12) is True


def test_allows_better_benefit():
    v1 = _campaign([_fixed_coupon("EX01", "12")])
    snapshot = build_campaign_snapshot(v1, ["chat1"], NOW)
    v2 = _campaign([_fixed_coupon("EX01", "20")])
    assert should_send_campaign(v2, [snapshot], NOW, 12) is True


def test_allows_early_and_active_publication():
    campaign = _campaign(
        [_fixed_coupon("EX01", "12")],
        start_at=NOW + timedelta(days=2),
    )
    scheduled_snapshot = build_campaign_snapshot(campaign, ["chat1"], NOW)

    active_now = NOW + timedelta(days=3)
    assert should_send_campaign(campaign, [scheduled_snapshot], active_now, 48) is True


def test_ignores_order_change():
    a = _fixed_coupon("EX01", "12")
    b = _fixed_coupon("EX02", "28")
    v1 = _campaign([a, b])
    snapshot = build_campaign_snapshot(v1, ["chat1"], NOW)
    v2 = _campaign([b, a])
    assert should_send_campaign(v2, [snapshot], NOW, 12) is False


def test_fingerprint_is_stable():
    campaign = _campaign([_fixed_coupon("EX01", "12")])
    assert build_content_fingerprint(campaign, NOW) == build_content_fingerprint(
        campaign, NOW
    )


def test_allows_after_window():
    campaign = _campaign([_fixed_coupon("EX01", "12")])
    snapshot = build_campaign_snapshot(campaign, ["chat1"], NOW - timedelta(hours=24))
    assert should_send_campaign(campaign, [snapshot], NOW, 12) is True
