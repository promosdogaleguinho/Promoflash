import logging
from datetime import datetime

from app.collectors.coupon_campaign_base import CouponCampaignCollector
from app.coupon_identity import build_coupon_key
from app.coupon_lifecycle import (
    filter_active_or_future_coupons,
    now_in_timezone,
    should_publish_campaign,
)
from app.models import Coupon, CouponCampaign

logger = logging.getLogger(__name__)


def _dedupe_coupons(coupons: list[Coupon]) -> list[Coupon]:
    unique: list[Coupon] = []
    seen: set[str] = set()
    for coupon in coupons:
        key = build_coupon_key(coupon)
        if key in seen:
            continue
        seen.add(key)
        unique.append(coupon)
    return unique


class ManualCouponCampaignCollector(CouponCampaignCollector):
    def __init__(
        self,
        campaigns: list[CouponCampaign],
        timezone_name: str,
    ) -> None:
        self._campaigns = campaigns
        self._timezone_name = timezone_name

    def collect(self, now: datetime | None = None) -> list[CouponCampaign]:
        current = now or now_in_timezone(self._timezone_name)
        publishable: list[CouponCampaign] = []

        for campaign in self._campaigns:
            if not campaign.enabled:
                continue

            campaign.coupons = _dedupe_coupons(
                filter_active_or_future_coupons(campaign.coupons, current)
            )

            if not should_publish_campaign(campaign, current):
                continue

            publishable.append(campaign)

        logger.info("Manual coupon campaigns loaded: %s", len(publishable))
        return publishable
