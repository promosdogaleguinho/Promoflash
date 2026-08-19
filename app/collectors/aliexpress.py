import logging

from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_mapper import (
    COLLECTOR_PRODUCT_SEARCH,
    map_aliexpress_product,
)
from app.collectors.base import BaseCollector
from app.collectors.keyword_quota import keyword_quotas

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 20


class AliExpressCollector(BaseCollector):
    def __init__(self, client: AliExpressClient, source_config: dict) -> None:
        self._client = client
        self._keywords = source_config.get("keywords", [])
        self._max_items = source_config.get("max_items_per_run", DEFAULT_PAGE_SIZE)

    def collect(self) -> list[dict]:
        collected: list[dict] = []
        seen_keys: set[str] = set()
        keywords = [keyword for keyword in self._keywords if str(keyword).strip()]
        if not keywords:
            logger.info("Product search collected: 0")
            return collected

        quotas = keyword_quotas(len(keywords), self._max_items)

        for keyword, quota in zip(keywords, quotas):
            if quota <= 0 or len(collected) >= self._max_items:
                continue

            taken = 0
            for raw in self._query_keyword(keyword, page_size=max(quota, 1)):
                if taken >= quota or len(collected) >= self._max_items:
                    break

                promotion = map_aliexpress_product(
                    raw,
                    keyword=keyword,
                    collector_type=COLLECTOR_PRODUCT_SEARCH,
                )
                if promotion is None:
                    continue

                dedup_key = promotion["external_id"] or promotion["url"]
                if dedup_key in seen_keys:
                    continue

                seen_keys.add(dedup_key)
                collected.append(promotion)
                taken += 1

        logger.info("Product search collected: %s", len(collected))
        return collected

    def _query_keyword(self, keyword: str, page_size: int) -> list[dict]:
        try:
            return self._client.product_query(
                keywords=keyword,
                page_no=1,
                page_size=page_size,
            )
        except Exception as exc:
            logger.error("Falha ao consultar AliExpress (keyword=%s): %s", keyword, exc)
            return []
