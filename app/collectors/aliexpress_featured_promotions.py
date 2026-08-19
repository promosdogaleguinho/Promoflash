import logging

from app.campaign_selection import select_featured_campaigns
from app.campaigns import get_campaign_display_name
from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_mapper import (
    COLLECTOR_FEATURED_PROMOTIONS,
    SOURCE_NAME,
    map_aliexpress_product,
)
from app.collectors.base import BaseCollector
from app.promotion_quality import TAG_ALIEXPRESS, TAG_OFFICIAL_CAMPAIGN

logger = logging.getLogger(__name__)

DEFAULT_MAX_CAMPAIGNS = 3
DEFAULT_MAX_ITEMS_PER_CAMPAIGN = 10
DEFAULT_MAX_ITEMS = 20
FALLBACK_CAMPAIGN_NAME = "Campanha AliExpress"


class AliExpressFeaturedPromotionsCollector(BaseCollector):
    def __init__(self, client: AliExpressClient, source_config: dict) -> None:
        self._client = client
        self._max_campaigns = source_config.get(
            "max_campaigns_per_run", DEFAULT_MAX_CAMPAIGNS
        )
        self._max_items_per_campaign = source_config.get(
            "max_items_per_campaign", DEFAULT_MAX_ITEMS_PER_CAMPAIGN
        )
        self._max_items = source_config.get("max_items_per_run", DEFAULT_MAX_ITEMS)
        self._allowed = source_config.get("allowed_campaigns", [])
        self._blocked = source_config.get("blocked_campaigns", [])
        self._preferred = source_config.get("preferred_campaign_patterns", [])
        self._blocked_patterns = source_config.get("blocked_campaign_patterns", [])

    def collect(self) -> list[dict]:
        campaigns = self._fetch_campaigns()
        selected = select_featured_campaigns(
            campaigns,
            max_campaigns=self._max_campaigns,
            allowed_campaigns=self._allowed,
            blocked_campaigns=self._blocked,
            preferred_patterns=self._preferred,
            blocked_patterns=self._blocked_patterns,
        )

        collected: list[dict] = []
        seen_ids: set[str] = set()

        for campaign in selected:
            if len(collected) >= self._max_items:
                break

            remaining = self._max_items - len(collected)
            products = self._collect_campaign_products(campaign, remaining)

            for promotion in products:
                external_id = promotion["external_id"]
                if external_id in seen_ids:
                    continue
                seen_ids.add(external_id)
                collected.append(promotion)
                if len(collected) >= self._max_items:
                    break

        logger.info("Featured products collected: %s", len(collected))
        return collected

    def _fetch_campaigns(self) -> list[dict]:
        try:
            campaigns = self._client.featured_promo_get()
        except Exception as exc:
            logger.error("Falha ao buscar campanhas AliExpress: %s", exc)
            campaigns = []

        logger.info("Featured campaigns collected: %s", len(campaigns))

        if not campaigns and self._allowed:
            campaigns = [
                {"promotion_id": None, "promotion_name": name, "raw": {}}
                for name in self._allowed
            ]
        return campaigns

    def _collect_campaign_products(
        self, campaign: dict, remaining: int
    ) -> list[dict]:
        promotion_name = campaign.get("promotion_name")
        promotion_id = campaign.get("promotion_id")
        display_name = get_campaign_display_name(promotion_name or "") or (
            promotion_name or FALLBACK_CAMPAIGN_NAME
        )
        limit = min(self._max_items_per_campaign, remaining)

        try:
            raw_products = self._client.featured_promo_products_get(
                promotion_name=promotion_name,
                promotion_id=promotion_id,
                page_no=1,
                page_size=limit,
            )
        except Exception as exc:
            logger.error(
                "Falha ao buscar produtos da campanha %s: %s", display_name, exc
            )
            return []

        mapped: list[dict] = []
        for raw in raw_products[:limit]:
            promotion = map_aliexpress_product(
                raw,
                collector_type=COLLECTOR_FEATURED_PROMOTIONS,
                is_official_campaign=True,
                campaign_name=display_name,
                extra_tags=[TAG_OFFICIAL_CAMPAIGN, display_name, TAG_ALIEXPRESS],
                extra_metadata={
                    "collector_type": COLLECTOR_FEATURED_PROMOTIONS,
                    "campaign_id": promotion_id,
                    "campaign_name": promotion_name,
                    "campaign_display_name": display_name,
                    "source_platform": SOURCE_NAME,
                },
            )
            if promotion is not None:
                mapped.append(promotion)
        return mapped
