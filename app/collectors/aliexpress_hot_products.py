import logging

from app.campaigns import DISPLAY_HOT_PRODUCT
from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_mapper import (
    COLLECTOR_HOT_PRODUCTS,
    SOURCE_NAME,
    map_aliexpress_product,
)
from app.collectors.base import BaseCollector
from app.promotion_quality import TAG_ALIEXPRESS

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITEMS = 20
DEFAULT_PAGE_SIZE = 20


class AliExpressHotProductsCollector(BaseCollector):
    def __init__(self, client: AliExpressClient, source_config: dict) -> None:
        self._client = client
        self._max_items = source_config.get("max_items_per_run", DEFAULT_MAX_ITEMS)
        self._page_size = source_config.get("page_size", DEFAULT_PAGE_SIZE)
        self._sort = source_config.get("sort")
        self._min_sale_price = source_config.get("min_sale_price")
        self._max_sale_price = source_config.get("max_sale_price")
        self._category_ids = source_config.get("category_ids")

    def collect(self) -> list[dict]:
        raw_products = self._query_hot_products()

        collected: list[dict] = []
        seen_ids: set[str] = set()

        for raw in raw_products:
            if len(collected) >= self._max_items:
                break

            promotion = map_aliexpress_product(
                raw,
                collector_type=COLLECTOR_HOT_PRODUCTS,
                is_official_campaign=False,
                campaign_name=None,
                extra_tags=[DISPLAY_HOT_PRODUCT, TAG_ALIEXPRESS],
                extra_metadata={
                    "collector_type": COLLECTOR_HOT_PRODUCTS,
                    "source_platform": SOURCE_NAME,
                },
            )
            if promotion is None:
                continue

            external_id = promotion["external_id"]
            if external_id in seen_ids:
                continue

            seen_ids.add(external_id)
            collected.append(promotion)

        logger.info("Hot products collected: %s", len(collected))
        return collected

    def _query_hot_products(self) -> list[dict]:
        try:
            return self._client.hot_product_query(
                page_no=1,
                page_size=self._page_size,
                category_ids=self._category_ids,
                sort=self._sort,
                min_sale_price=self._min_sale_price,
                max_sale_price=self._max_sale_price,
            )
        except Exception as exc:
            logger.error("Falha ao consultar Hot Products AliExpress: %s", exc)
            return []
