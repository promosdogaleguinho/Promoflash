from datetime import datetime, timedelta

from app.coupon_lifecycle import (
    filter_active_or_future_coupons,
    get_timezone,
    is_coupon_active,
    is_coupon_expired,
    now_in_timezone,
    should_publish_campaign,
)
from app.models import Coupon, CouponCampaign

TZ = get_timezone("America/Sao_Paulo")


def _now() -> datetime:
    return datetime(2030, 1, 10, 12, 0, 0, tzinfo=TZ)


def test_active_coupon():
    coupon = Coupon(
        source="s",
        start_at=_now() - timedelta(days=1),
        end_at=_now() + timedelta(days=1),
    )
    assert is_coupon_active(coupon, _now()) is True


def test_future_coupon_is_not_active_but_not_expired():
    coupon = Coupon(source="s", start_at=_now() + timedelta(days=1))
    assert is_coupon_active(coupon, _now()) is False
    assert is_coupon_expired(coupon, _now()) is False


def test_expired_coupon():
    coupon = Coupon(source="s", end_at=_now() - timedelta(hours=1))
    assert is_coupon_expired(coupon, _now()) is True
    assert is_coupon_active(coupon, _now()) is False


def test_disabled_campaign_not_published():
    campaign = CouponCampaign(
        source="s",
        campaign_id="c1",
        title="X",
        enabled=False,
        coupons=[Coupon(source="s", code="A")],
    )
    assert should_publish_campaign(campaign, _now()) is False


def test_early_announcement_before_campaign():
    campaign = CouponCampaign(
        source="s",
        campaign_id="c1",
        title="X",
        coupons=[Coupon(source="s", code="A")],
        start_at=_now() + timedelta(days=2),
        announcement_at=_now() - timedelta(hours=1),
        announce_before_start=True,
    )
    assert should_publish_campaign(campaign, _now()) is True


def test_campaign_not_announced_before_time():
    campaign = CouponCampaign(
        source="s",
        campaign_id="c1",
        title="X",
        coupons=[Coupon(source="s", code="A")],
        start_at=_now() + timedelta(days=2),
        announcement_at=_now() + timedelta(hours=1),
        announce_before_start=True,
    )
    assert should_publish_campaign(campaign, _now()) is False


def test_campaign_published_when_active():
    campaign = CouponCampaign(
        source="s",
        campaign_id="c1",
        title="X",
        coupons=[Coupon(source="s", code="A")],
        start_at=_now() - timedelta(hours=1),
    )
    assert should_publish_campaign(campaign, _now()) is True


def test_timezone_default():
    now = now_in_timezone()
    assert now.tzinfo is not None
    assert "Sao_Paulo" in str(now.tzinfo)


def test_missing_dates_do_not_break():
    coupon = Coupon(source="s", code="A")
    assert is_coupon_active(coupon, _now()) is True
    assert is_coupon_expired(coupon, _now()) is False


def test_expired_coupons_are_filtered():
    active = Coupon(source="s", code="A", end_at=_now() + timedelta(days=1))
    expired = Coupon(source="s", code="B", end_at=_now() - timedelta(days=1))
    remaining = filter_active_or_future_coupons([active, expired], _now())
    assert active in remaining
    assert expired not in remaining
