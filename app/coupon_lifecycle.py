from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import Coupon, CouponCampaign

DEFAULT_TIMEZONE = "America/Sao_Paulo"


def get_timezone(timezone_name: str = DEFAULT_TIMEZONE) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_in_timezone(timezone_name: str = DEFAULT_TIMEZONE) -> datetime:
    return datetime.now(get_timezone(timezone_name))


def _ensure_aware(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    return value


def is_coupon_expired(coupon: Coupon, now: datetime) -> bool:
    if coupon.end_at is None:
        return False
    end_at = _ensure_aware(coupon.end_at, now)
    return now > end_at


def is_coupon_active(coupon: Coupon, now: datetime) -> bool:
    if is_coupon_expired(coupon, now):
        return False
    if coupon.start_at is None:
        return True
    start_at = _ensure_aware(coupon.start_at, now)
    return now >= start_at


def filter_active_or_future_coupons(
    coupons: list[Coupon], now: datetime
) -> list[Coupon]:
    return [coupon for coupon in coupons if not is_coupon_expired(coupon, now)]


def _campaign_ended(campaign: CouponCampaign, now: datetime) -> bool:
    if campaign.end_at is None:
        return False
    end_at = _ensure_aware(campaign.end_at, now)
    return now > end_at


def _is_informational(campaign: CouponCampaign) -> bool:
    return bool(campaign.metadata.get("informational"))


def _can_announce_before_start(campaign: CouponCampaign, now: datetime) -> bool:
    if not campaign.announce_before_start:
        return False
    if campaign.announcement_at is None:
        return False
    announcement_at = _ensure_aware(campaign.announcement_at, now)
    return now >= announcement_at


def should_publish_campaign(campaign: CouponCampaign, now: datetime) -> bool:
    if not campaign.enabled:
        return False
    if _campaign_ended(campaign, now):
        return False

    usable_coupons = filter_active_or_future_coupons(campaign.coupons, now)
    if campaign.coupons and not usable_coupons and not _is_informational(campaign):
        return False
    if not campaign.coupons and not _is_informational(campaign):
        return False

    if campaign.start_at is None:
        return True

    start_at = _ensure_aware(campaign.start_at, now)
    if now >= start_at:
        return True

    return _can_announce_before_start(campaign, now)


def is_campaign_expired(campaign: CouponCampaign, now: datetime) -> bool:
    return _campaign_ended(campaign, now)


def is_campaign_scheduled(campaign: CouponCampaign, now: datetime) -> bool:
    if campaign.start_at is None:
        return False
    start_at = _ensure_aware(campaign.start_at, now)
    return now < start_at
