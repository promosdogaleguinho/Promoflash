import logging
from datetime import datetime

from app.campaign_selection import select_featured_campaigns
from app.campaigns import get_campaign_display_name
from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_coupon_extractor import extract_aliexpress_coupons
from app.collectors.coupon_campaign_base import CouponCampaignCollector
from app.coupon_identity import build_coupon_key, build_publication_key
from app.coupon_lifecycle import (
    filter_active_or_future_coupons,
    now_in_timezone,
    should_publish_campaign,
)
from app.models import Coupon, CouponCampaign, CouponScopeType

logger = logging.getLogger(__name__)

SOURCE_NAME = "aliexpress"
DEFAULT_TIMEZONE = "America/Sao_Paulo"
DEFAULT_MAX_CAMPAIGNS = 3
DEFAULT_CAMPAIGN_TITLE = "Cupons AliExpress"


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


def _has_publishable_coupon(coupon: Coupon) -> bool:
    return bool(
        coupon.code
        or coupon.coupon_url
        or coupon.affiliate_url
        or coupon.description
        or coupon.discount_value is not None
        or coupon.discount_percentage is not None
    )


def _campaign_title(promotion_name: object) -> str:
    name = str(promotion_name or "").strip()
    if not name or name.upper().startswith("AEB_"):
        return DEFAULT_CAMPAIGN_TITLE
    return get_campaign_display_name(name) or DEFAULT_CAMPAIGN_TITLE


class AliExpressApiCouponCampaignCollector(CouponCampaignCollector):
    """Coleta CouponCampaign apenas a partir de retornos oficiais da Affiliate API.

    Publica somente códigos presentes no payload da própria campanha.
    Cupons encontrados em produtos permanecem no pipeline de produtos.
    """

    def __init__(
        self,
        client: AliExpressClient,
        source_config: dict | None = None,
        timezone_name: str = DEFAULT_TIMEZONE,
    ) -> None:
        config = source_config or {}
        self._client = client
        self._timezone_name = timezone_name
        self._max_campaigns = config.get("max_campaigns_per_run", DEFAULT_MAX_CAMPAIGNS)
        self._allowed = config.get("allowed_campaigns", [])
        self._blocked = config.get("blocked_campaigns", [])
        self._preferred = config.get("preferred_campaign_patterns", [])
        self._blocked_patterns = config.get("blocked_campaign_patterns", [])

    def collect(self, now: datetime | None = None) -> list[CouponCampaign]:
        current = now or now_in_timezone(self._timezone_name)
        campaigns = self._fetch_featured_campaigns()
        selected = select_featured_campaigns(
            campaigns,
            max_campaigns=self._max_campaigns,
            allowed_campaigns=self._allowed,
            blocked_campaigns=self._blocked,
            preferred_patterns=self._preferred,
            blocked_patterns=self._blocked_patterns,
        )

        publishable: list[CouponCampaign] = []
        seen_publication_keys: set[str] = set()
        stats = {
            "featured_campaigns": len(campaigns),
            "selected_campaigns": len(selected),
            "campaign_level_coupon_structures": 0,
            "products_fetched": 0,
            "products_with_promo_code_info": 0,
            "product_details_queried": 0,
            "unique_coupon_codes": 0,
            "campaigns_with_coupons": 0,
        }

        for campaign in selected:
            built, campaign_stats = self._build_campaign_from_api(campaign)
            stats["products_fetched"] += campaign_stats["products_fetched"]
            stats["products_with_promo_code_info"] += campaign_stats[
                "products_with_promo_code_info"
            ]
            stats["product_details_queried"] += campaign_stats[
                "product_details_queried"
            ]
            stats["campaign_level_coupon_structures"] += campaign_stats[
                "campaign_level_coupon_structures"
            ]

            if built is None:
                continue

            built.coupons = _dedupe_coupons(
                filter_active_or_future_coupons(built.coupons, current)
            )
            if not built.coupons or not should_publish_campaign(built, current):
                continue

            publication_key = build_publication_key(built)
            if publication_key in seen_publication_keys:
                continue
            seen_publication_keys.add(publication_key)

            stats["campaigns_with_coupons"] += 1
            stats["unique_coupon_codes"] += sum(1 for coupon in built.coupons if coupon.code)
            publishable.append(built)

        logger.info(
            "AliExpress API coupon campaigns: featured=%s selected=%s "
            "products=%s details=%s with_promo_code_info=%s "
            "campaign_coupon_structures=%s campaigns_with_coupons=%s codes=%s",
            stats["featured_campaigns"],
            stats["selected_campaigns"],
            stats["products_fetched"],
            stats["product_details_queried"],
            stats["products_with_promo_code_info"],
            stats["campaign_level_coupon_structures"],
            stats["campaigns_with_coupons"],
            stats["unique_coupon_codes"],
        )
        return publishable

    def _fetch_featured_campaigns(self) -> list[dict]:
        try:
            return self._client.featured_promo_get()
        except Exception as exc:
            logger.warning("Falha não bloqueante em featuredpromo.get: %s", exc)
            return []

    def _build_campaign_from_api(
        self, campaign: dict
    ) -> tuple[CouponCampaign | None, dict]:
        stats = {
            "products_fetched": 0,
            "products_with_promo_code_info": 0,
            "product_details_queried": 0,
            "campaign_level_coupon_structures": 0,
        }

        promotion_id = campaign.get("promotion_id")
        promotion_name = campaign.get("promotion_name")
        display_name = _campaign_title(promotion_name)
        campaign_id = str(promotion_id or promotion_name or display_name)

        campaign_coupons = extract_aliexpress_coupons({}, campaign)
        stats["campaign_level_coupon_structures"] = len(campaign_coupons)
        coupons = _dedupe_coupons(campaign_coupons)
        coupons = [coupon for coupon in coupons if _has_publishable_coupon(coupon)]
        if not coupons:
            return None, stats

        for coupon in coupons:
            coupon.source = SOURCE_NAME
            coupon.campaign_id = campaign_id
            coupon.campaign_name = display_name
            if coupon.scope_type == CouponScopeType.UNKNOWN:
                coupon.scope_type = CouponScopeType.CAMPAIGN
                coupon.scope_value = campaign_id
            coupon.metadata["attachment_reason"] = "api_campaign_response"
            coupon.metadata["source_collector"] = "aliexpress_api_coupon_campaigns"

        return (
            CouponCampaign(
                source=SOURCE_NAME,
                campaign_id=campaign_id,
                title=display_name,
                description=None,
                campaign_name=display_name,
                coupons=coupons,
                category="geral",
                tags=["Campanha oficial", "Cupons"],
                enabled=True,
                metadata={
                    "source_collector": "aliexpress_api_coupon_campaigns",
                    "promotion_id": promotion_id,
                    "promotion_name": promotion_name,
                    "products_sampled": stats["products_fetched"],
                    "product_details_queried": stats["product_details_queried"],
                },
            ),
            stats,
        )
