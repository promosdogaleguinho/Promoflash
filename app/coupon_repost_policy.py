from datetime import datetime, timedelta

from app.coupon_identity import (
    build_campaign_fingerprint,
    build_coupon_key,
    build_publication_key,
)
from app.coupon_lifecycle import is_campaign_scheduled
from app.models import CouponCampaign, SentCouponCampaignSnapshot

DEFAULT_WINDOW_HOURS = 12


def _campaign_phase(campaign: CouponCampaign, now: datetime) -> str:
    return "scheduled" if is_campaign_scheduled(campaign, now) else "active"


def build_content_fingerprint(campaign: CouponCampaign, now: datetime) -> str:
    phase = _campaign_phase(campaign, now)
    return f"{phase}:{build_campaign_fingerprint(campaign)}"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _within_window(published_at: str, now: datetime, window_hours: int) -> bool:
    published = _parse_datetime(published_at)
    if published.tzinfo is None and now.tzinfo is not None:
        published = published.replace(tzinfo=now.tzinfo)
    return published >= now - timedelta(hours=window_hours)


def should_send_campaign(
    campaign: CouponCampaign,
    snapshots: list[SentCouponCampaignSnapshot],
    now: datetime,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> bool:
    publication_key = build_publication_key(campaign)
    fingerprint = build_content_fingerprint(campaign, now)

    for snapshot in snapshots:
        if snapshot.publication_key != publication_key:
            continue
        if not _within_window(snapshot.published_at, now, window_hours):
            continue
        if snapshot.content_fingerprint == fingerprint:
            return False

    return True


def build_campaign_snapshot(
    campaign: CouponCampaign,
    destination_ids: list[str],
    now: datetime,
) -> SentCouponCampaignSnapshot:
    coupon_keys = sorted(build_coupon_key(coupon) for coupon in campaign.coupons)
    return SentCouponCampaignSnapshot(
        publication_key=build_publication_key(campaign),
        campaign_id=campaign.campaign_id,
        source=campaign.source,
        coupon_keys=coupon_keys,
        published_at=now.isoformat(),
        content_fingerprint=build_content_fingerprint(campaign, now),
        start_at=campaign.start_at.isoformat() if campaign.start_at else None,
        end_at=campaign.end_at.isoformat() if campaign.end_at else None,
        destination_ids=list(destination_ids),
    )
