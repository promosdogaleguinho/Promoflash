import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.awin_landing_enrichment import enrich_offers_from_landing
from app.awin_product_feed import (
    AwinFeedEnrichmentMetrics,
    ProductFeedIndex,
    enrich_offers_with_feed,
    parse_enhanced_feed_jsonl,
    parse_product_feed,
)
from app.clients.awin import AwinClient, AwinError, AwinHttpError
from app.clients.awin_product_feed import (
    AwinProductFeedClient,
    sanitize_feed_url_for_log,
)
from app.collectors.awin_mapper import (
    AwinAdvertiserConfig,
    map_awin_offer,
)
from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

DEFAULT_FEED_LOCALE = "pt_BR"


@dataclass
class AwinCollectorMetrics:
    pages_fetched: int = 0
    offers_received: int = 0
    vouchers_collected: int = 0
    promotions_collected: int = 0
    invalid_offers_skipped: int = 0
    skipped_by_advertiser: int = 0
    skipped_by_date_status: int = 0
    http_errors: int = 0
    final_offers: int = 0
    feed_rows_parsed: int = 0
    feed_products_indexed: int = 0
    offers_enriched: int = 0
    offers_without_product_match: int = 0
    offers_with_image: int = 0
    offers_with_current_price: int = 0
    offers_with_old_price: int = 0
    feed_download_failed: bool = False
    feed_parsing_failed: bool = False
    feed_source: str | None = None
    landing_enriched: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def increment_reason(self, reason: str) -> None:
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1


class AwinCollector(BaseCollector):
    def __init__(
        self,
        client: AwinClient,
        advertisers: list[AwinAdvertiserConfig],
        membership: str = "joined",
        region_codes: list[str] | None = None,
        status: str = "active",
        offer_type: str = "all",
        page_size: int = 200,
        max_items_per_run: int | None = None,
        product_feed_url: str | None = None,
        feed_locale: str = DEFAULT_FEED_LOCALE,
        now: datetime | None = None,
    ) -> None:
        self._client = client
        self._advertisers = [item for item in advertisers if item.enabled]
        self._advertisers_by_id = {item.id: item for item in self._advertisers}
        self._membership = membership
        self._region_codes = region_codes or ["BR"]
        self._status = status
        self._offer_type = offer_type
        self._page_size = page_size
        self._max_items = max_items_per_run
        self._product_feed_url = (product_feed_url or "").strip() or None
        self._feed_locale = (feed_locale or DEFAULT_FEED_LOCALE).strip() or DEFAULT_FEED_LOCALE
        self._now = now
        self.metrics = AwinCollectorMetrics()

    def collect(self) -> list[dict]:
        self.metrics = AwinCollectorMetrics()
        if not self._advertisers:
            logger.warning("Awin sem anunciantes habilitados; coleta ignorada.")
            return []

        now = self._now or datetime.now(timezone.utc)
        advertiser_ids = [item.id for item in self._advertisers]

        raw_offers, enhanced_index, csv_index = self._fetch_offers_and_feed_indexes(
            advertiser_ids
        )
        self.metrics.pages_fetched = self._client.pages_fetched
        self.metrics.offers_received = len(raw_offers)

        collected: list[dict] = []
        seen_ids: set[str] = set()

        for raw in raw_offers:
            mapped, reason = map_awin_offer(raw, self._advertisers_by_id, now)
            if mapped is None:
                self.metrics.invalid_offers_skipped += 1
                self.metrics.increment_reason(reason or "unknown")
                if reason in {
                    "advertiser_not_enabled",
                    "advertiser_not_joined",
                    "invalid_advertiser_id",
                    "missing_advertiser",
                }:
                    self.metrics.skipped_by_advertiser += 1
                elif reason in {
                    "outside_date_window",
                    "invalid_status",
                }:
                    self.metrics.skipped_by_date_status += 1
                continue

            external_id = mapped["external_id"]
            if external_id in seen_ids:
                self.metrics.increment_reason("duplicate_promotion_id")
                continue
            seen_ids.add(external_id)
            collected.append(mapped)

        collected = self._apply_run_limit(collected)
        collected = self._enrich_with_feed_cascade(collected, enhanced_index, csv_index)
        collected = self._enrich_with_landing_pages(collected)

        self.metrics.final_offers = len(collected)
        self.metrics.vouchers_collected = sum(
            1 for item in collected if item["kind"] == "voucher"
        )
        self.metrics.promotions_collected = sum(
            1 for item in collected if item["kind"] == "promotion"
        )
        logger.info(
            "Awin offers collected=%s vouchers=%s promotions=%s "
            "feed_source=%s enriched=%s landing_enriched=%s without_match=%s "
            "with_image=%s with_price=%s invalid_skipped=%s pages=%s",
            self.metrics.final_offers,
            self.metrics.vouchers_collected,
            self.metrics.promotions_collected,
            self.metrics.feed_source,
            self.metrics.offers_enriched,
            self.metrics.landing_enriched,
            self.metrics.offers_without_product_match,
            self.metrics.offers_with_image,
            self.metrics.offers_with_current_price,
            self.metrics.invalid_offers_skipped,
            self.metrics.pages_fetched,
        )
        return collected

    def _fetch_offers_and_feed_indexes(
        self,
        advertiser_ids: list[int],
    ) -> tuple[list[dict], ProductFeedIndex, ProductFeedIndex]:
        def fetch_offers() -> list[dict]:
            return self._client.fetch_promotions(
                advertiser_ids=advertiser_ids,
                membership=self._membership,
                region_codes=self._region_codes,
                status=self._status,
                offer_type=self._offer_type,
                page_size=self._page_size,
            )

        def fetch_feed_indexes() -> tuple[ProductFeedIndex, ProductFeedIndex]:
            return self._load_product_feed_indexes(advertiser_ids)

        with ThreadPoolExecutor(max_workers=2) as executor:
            offers_future = executor.submit(fetch_offers)
            feed_future = executor.submit(fetch_feed_indexes)
            try:
                enhanced_index, csv_index = feed_future.result()
            except Exception as exc:
                self.metrics.feed_download_failed = True
                logger.error("Awin product feed load failed: %s", exc)
                enhanced_index, csv_index = ProductFeedIndex(), ProductFeedIndex()
            try:
                raw_offers = offers_future.result()
            except AwinError as exc:
                self.metrics.http_errors += 1
                logger.error("Awin coleta falhou: %s", exc)
                raise

        return raw_offers, enhanced_index, csv_index

    def _load_product_feed_indexes(
        self,
        advertiser_ids: list[int],
    ) -> tuple[ProductFeedIndex, ProductFeedIndex]:
        enhanced_metrics = AwinFeedEnrichmentMetrics()
        csv_metrics = AwinFeedEnrichmentMetrics()
        enhanced = ProductFeedIndex()
        csv_index = ProductFeedIndex()

        for advertiser_id in advertiser_ids:
            try:
                content = self._client.fetch_enhanced_retail_feed(
                    advertiser_id,
                    locale=self._feed_locale,
                )
                partial = parse_enhanced_feed_jsonl(
                    content,
                    advertiser_id,
                    enhanced_metrics,
                )
                for product in partial.by_merchant_product.values():
                    enhanced.add(product)
                logger.info(
                    "Awin enhanced feed ok advertiser=%s products=%s",
                    advertiser_id,
                    len(partial),
                )
            except AwinHttpError as exc:
                logger.info(
                    "Awin enhanced feed indisponível advertiser=%s locale=%s (%s).",
                    advertiser_id,
                    self._feed_locale,
                    exc,
                )
            except Exception as exc:
                logger.warning(
                    "Awin enhanced feed falhou advertiser=%s: %s",
                    advertiser_id,
                    exc,
                )

        if self._product_feed_url:
            try:
                content = AwinProductFeedClient(self._product_feed_url).download()
                csv_index = parse_product_feed(content, csv_metrics)
                self.metrics.feed_parsing_failed = csv_metrics.parsing_failed
                logger.info(
                    "Awin Create-a-Feed CSV indexed products=%s rows=%s",
                    len(csv_index),
                    csv_metrics.rows_parsed,
                )
            except Exception as exc:
                self.metrics.feed_download_failed = True
                logger.error(
                    "Awin Create-a-Feed download failed url=%s error=%s",
                    sanitize_feed_url_for_log(self._product_feed_url),
                    exc,
                )
        elif not enhanced:
            logger.warning(
                "Nenhum Product Feed disponível (Enhanced vazia/indisponível e "
                "AWIN_PRODUCT_FEED_URL ausente). Ofertas sem preço/imagem."
            )
            self.metrics.feed_download_failed = True

        sources: list[str] = []
        if enhanced:
            sources.append("enhanced_api")
        if csv_index:
            sources.append("create_a_feed_csv")
        self.metrics.feed_source = "+".join(sources) if sources else None
        self.metrics.feed_rows_parsed = (
            enhanced_metrics.rows_parsed + csv_metrics.rows_parsed
        )
        self.metrics.feed_products_indexed = len(enhanced) + len(csv_index)
        return enhanced, csv_index

    def _enrich_with_feed_cascade(
        self,
        offers: list[dict],
        enhanced_index: ProductFeedIndex,
        csv_index: ProductFeedIndex,
    ) -> list[dict]:
        if not offers:
            return offers

        enhanced_metrics = AwinFeedEnrichmentMetrics()
        csv_metrics = AwinFeedEnrichmentMetrics()
        current = offers

        if enhanced_index:
            current = enrich_offers_with_feed(current, enhanced_index, enhanced_metrics)
            logger.info(
                "Awin enhanced enrichment filled=%s without_match=%s "
                "with_image=%s with_price=%s",
                enhanced_metrics.offers_enriched,
                enhanced_metrics.offers_without_match,
                enhanced_metrics.offers_with_image,
                enhanced_metrics.offers_with_current_price,
            )

        pending_after_enhanced = [
            item
            for item in current
            if item.get("price") is None or not item.get("image_url")
        ]
        if csv_index and pending_after_enhanced:
            current = enrich_offers_with_feed(current, csv_index, csv_metrics)
            logger.info(
                "Awin CSV enrichment filled=%s without_match=%s "
                "with_image=%s with_price=%s",
                csv_metrics.offers_enriched,
                csv_metrics.offers_without_match,
                csv_metrics.offers_with_image,
                csv_metrics.offers_with_current_price,
            )
        elif csv_index and not pending_after_enhanced:
            logger.info(
                "Awin CSV indexed=%s skipped: Enhanced já preencheu preço e imagem",
                len(csv_index),
            )

        self.metrics.offers_enriched = (
            enhanced_metrics.offers_enriched + csv_metrics.offers_enriched
        )
        self.metrics.offers_without_product_match = sum(
            1
            for item in current
            if item.get("price") is None and not item.get("image_url")
        )
        self.metrics.offers_with_image = sum(
            1 for item in current if item.get("image_url")
        )
        self.metrics.offers_with_current_price = sum(
            1 for item in current if item.get("price") is not None
        )
        self.metrics.offers_with_old_price = sum(
            1 for item in current if item.get("old_price") is not None
        )
        if (
            self.metrics.offers_enriched == 0
            and (enhanced_index or csv_index)
        ):
            logger.warning(
                "Awin feeds indexed enhanced=%s csv=%s but no offers enriched. "
                "Ofertas sem /produto/{{id}} ou fora do catálogo.",
                len(enhanced_index),
                len(csv_index),
            )
        return current

    def _enrich_with_landing_pages(self, offers: list[dict]) -> list[dict]:
        pending = [
            item
            for item in offers
            if not item.get("image_url") or item.get("price") is None
        ]
        if not pending:
            return offers

        landing_metrics = AwinFeedEnrichmentMetrics()
        enriched = enrich_offers_from_landing(offers, landing_metrics)
        self.metrics.landing_enriched = landing_metrics.offers_enriched
        self.metrics.offers_enriched += landing_metrics.offers_enriched
        self.metrics.offers_with_image = sum(
            1 for item in enriched if item.get("image_url")
        )
        self.metrics.offers_with_current_price = sum(
            1 for item in enriched if item.get("price") is not None
        )
        self.metrics.offers_with_old_price = sum(
            1 for item in enriched if item.get("old_price") is not None
        )
        if landing_metrics.offers_enriched:
            logger.info(
                "Awin landing enrichment filled=%s with_image=%s with_price=%s",
                landing_metrics.offers_enriched,
                landing_metrics.offers_with_image,
                landing_metrics.offers_with_current_price,
            )
        return enriched

    def _apply_run_limit(self, items: list[dict]) -> list[dict]:
        if self._max_items is None or len(items) <= self._max_items:
            return items

        vouchers = [item for item in items if item.get("kind") == "voucher"]
        promotions = [item for item in items if item.get("kind") != "voucher"]

        voucher_quota = min(len(vouchers), max(1, self._max_items // 2))
        if not vouchers:
            voucher_quota = 0

        selected = vouchers[:voucher_quota]
        remaining = self._max_items - len(selected)
        selected.extend(promotions[:remaining])

        if len(selected) < self._max_items:
            used_ids = {item["external_id"] for item in selected}
            for item in vouchers[voucher_quota:]:
                if len(selected) >= self._max_items:
                    break
                if item["external_id"] in used_ids:
                    continue
                selected.append(item)
                used_ids.add(item["external_id"])

        logger.info(
            "Awin run limit applied max=%s selected=%s vouchers=%s promotions=%s",
            self._max_items,
            len(selected),
            sum(1 for item in selected if item.get("kind") == "voucher"),
            sum(1 for item in selected if item.get("kind") == "promotion"),
        )
        return selected
