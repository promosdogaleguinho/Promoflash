import logging
from dataclasses import dataclass, field

from app.clients.shopee_affiliate import (
    ShopeeAffiliateClient,
    ShopeeAffiliateError,
)
from app.collectors.base import BaseCollector
from app.collectors.keyword_quota import keyword_quotas
from app.collectors.shopee_mapper import map_shopee_product

logger = logging.getLogger(__name__)


@dataclass
class ShopeeCollectorMetrics:
    pages_fetched: int = 0
    nodes_received: int = 0
    products_normalized: int = 0
    duplicates_across_pages: int = 0
    products_without_price: int = 0
    products_single_price: int = 0
    products_price_range: int = 0
    products_without_offer_link: int = 0
    shops_mall: int = 0
    shops_star: int = 0
    shops_star_plus: int = 0
    shops_standard: int = 0
    products_not_started: int = 0
    products_expired: int = 0
    http_errors: int = 0
    graphql_errors: int = 0
    auth_failures: int = 0
    retries: int = 0
    final_promotions: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def increment_reason(self, reason: str) -> None:
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1


class ShopeeCollector(BaseCollector):
    def __init__(
        self,
        client: ShopeeAffiliateClient,
        keywords: list[str] | None = None,
        max_items_per_run: int = 20,
        page_limit: int | None = None,
        max_pages: int = 5,
    ) -> None:
        self._client = client
        self._keywords = keywords or []
        self._max_items = max_items_per_run
        self._page_limit = page_limit or client.page_limit
        self._max_pages = max_pages
        self.metrics = ShopeeCollectorMetrics()

    def collect(self) -> list[dict]:
        self.metrics = ShopeeCollectorMetrics()
        collected: list[dict] = []
        seen_ids: set[str] = set()
        keywords = self._keywords or [None]
        quotas = keyword_quotas(len(keywords), self._max_items)

        for keyword, quota in zip(keywords, quotas):
            if quota <= 0 or len(collected) >= self._max_items:
                continue
            before = len(collected)
            try:
                self._collect_keyword(
                    keyword,
                    collected,
                    seen_ids,
                    max_for_keyword=quota,
                )
            except ShopeeAffiliateError as exc:
                self._record_client_error(exc)
                logger.error(
                    "Falha ao coletar Shopee (keyword=%s): %s",
                    keyword,
                    type(exc).__name__,
                )
            except Exception as exc:
                logger.error(
                    "Erro inesperado no collector Shopee (keyword=%s): %s",
                    keyword,
                    exc,
                )
            added = len(collected) - before
            logger.info(
                "Shopee keyword=%s quota=%s collected=%s",
                keyword,
                quota,
                added,
            )

        self.metrics.final_promotions = len(collected)
        self.metrics.http_errors += self._client.metrics.get("http_errors", 0)
        self.metrics.graphql_errors += self._client.metrics.get("graphql_errors", 0)
        self.metrics.auth_failures += self._client.metrics.get("auth_failures", 0)
        self.metrics.retries += self._client.metrics.get("retries", 0)

        logger.info(
            "Shopee collected=%s pages=%s nodes=%s duplicates=%s "
            "rejections=%s mall=%s star=%s star_plus=%s standard=%s",
            self.metrics.final_promotions,
            self.metrics.pages_fetched,
            self.metrics.nodes_received,
            self.metrics.duplicates_across_pages,
            self.metrics.rejection_reasons,
            self.metrics.shops_mall,
            self.metrics.shops_star,
            self.metrics.shops_star_plus,
            self.metrics.shops_standard,
        )
        return collected

    def _collect_keyword(
        self,
        keyword: str | None,
        collected: list[dict],
        seen_ids: set[str],
        max_for_keyword: int,
    ) -> None:
        previous_page_fingerprint: str | None = None
        added_for_keyword = 0

        for page in range(1, self._max_pages + 1):
            if added_for_keyword >= max_for_keyword or len(collected) >= self._max_items:
                break

            result = self._client.product_offer_v2(
                keyword=keyword,
                page=page,
                limit=self._page_limit,
            )
            self.metrics.pages_fetched += 1

            nodes = result.get("nodes") or []
            page_info = result.get("pageInfo") or {}
            scroll_id = page_info.get("scrollId")
            if scroll_id:
                logger.debug(
                    "Shopee page=%s scrollId presente (ignorado na paginação)",
                    page,
                )

            fingerprint = _page_fingerprint(nodes)
            if previous_page_fingerprint is not None and fingerprint == previous_page_fingerprint:
                logger.warning(
                    "Shopee página repetida detectada (page=%s keyword=%s); encerrando.",
                    page,
                    keyword,
                )
                break
            previous_page_fingerprint = fingerprint

            if not nodes:
                break

            self.metrics.nodes_received += len(nodes)
            for node in nodes:
                if added_for_keyword >= max_for_keyword or len(collected) >= self._max_items:
                    break
                before = len(collected)
                self._ingest_node(node, keyword, collected, seen_ids)
                if len(collected) > before:
                    added_for_keyword += 1

            if not page_info.get("hasNextPage"):
                break

    def _ingest_node(
        self,
        node: dict,
        keyword: str | None,
        collected: list[dict],
        seen_ids: set[str],
    ) -> None:
        if not isinstance(node, dict):
            return

        offer_link = str(node.get("offerLink") or "").strip()
        if not offer_link:
            self.metrics.products_without_offer_link += 1
            self.metrics.increment_reason("sem_offer_link")

        mapped = map_shopee_product(node, keyword=keyword)
        if mapped is None:
            self._record_rejection_from_node(node)
            return

        external_id = mapped["external_id"]
        if external_id in seen_ids:
            self.metrics.duplicates_across_pages += 1
            return

        seen_ids.add(external_id)
        collected.append(mapped)
        self.metrics.products_normalized += 1
        self._record_shop_and_price_metrics(mapped)

    def _record_rejection_from_node(self, node: dict) -> None:
        from app.collectors.shopee_mapper import (
            evaluate_period,
            resolve_main_price,
            to_decimal,
            to_int,
        )

        if to_int(node.get("itemId")) is None or to_int(node.get("shopId")) is None:
            self.metrics.increment_reason("identidade_invalida")
            return
        if not str(node.get("productName") or "").strip():
            self.metrics.increment_reason("sem_titulo")
            return
        if not str(node.get("offerLink") or "").strip():
            return
        price = resolve_main_price(
            to_decimal(node.get("price")),
            to_decimal(node.get("priceMin")),
        )
        if price is None:
            self.metrics.products_without_price += 1
            self.metrics.increment_reason("sem_preco")
            return
        discount = to_decimal(node.get("priceDiscountRate"))
        if discount is None or discount <= 0:
            self.metrics.increment_reason("sem_desconto")
            return
        period = evaluate_period(node.get("periodStartTime"), node.get("periodEndTime"))
        if period["not_started"]:
            self.metrics.products_not_started += 1
            self.metrics.increment_reason("nao_iniciado")
            return
        if period["expired"]:
            self.metrics.products_expired += 1
            self.metrics.increment_reason("expirado")

    def _record_shop_and_price_metrics(self, mapped: dict) -> None:
        metadata = mapped.get("metadata") or {}
        if metadata.get("has_price_range"):
            self.metrics.products_price_range += 1
        else:
            self.metrics.products_single_price += 1

        shop_tier = metadata.get("shop_tier")
        if shop_tier == "mall":
            self.metrics.shops_mall += 1
        elif shop_tier == "star_plus":
            self.metrics.shops_star_plus += 1
        elif shop_tier == "star":
            self.metrics.shops_star += 1
        else:
            self.metrics.shops_standard += 1

    def _record_client_error(self, exc: ShopeeAffiliateError) -> None:
        from app.clients.shopee_affiliate import (
            ShopeeAuthError,
            ShopeeGraphQLError,
            ShopeeHttpError,
            ShopeeTimeoutError,
        )

        if isinstance(exc, ShopeeAuthError):
            self.metrics.auth_failures += 1
        elif isinstance(exc, ShopeeGraphQLError):
            self.metrics.graphql_errors += 1
        elif isinstance(exc, (ShopeeHttpError, ShopeeTimeoutError)):
            self.metrics.http_errors += 1


def _page_fingerprint(nodes: list[dict]) -> str:
    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        parts.append(f"{node.get('shopId')}:{node.get('itemId')}")
    return "|".join(parts)
