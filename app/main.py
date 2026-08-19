import json
import logging
from decimal import Decimal
from pathlib import Path

from app.awin_config import load_awin_advertisers
from app.awin_formatter import campaign_offer_from_dict, format_campaign_offer
from app.awin_persistence import AwinOfferPersistence
from app.awin_repost_policy import (
    build_offer_snapshot,
    should_send_offer_to_destination,
)
from app.category_resolver import (
    resolve_campaign_offer_category,
    resolve_category,
)
from app.clients.aliexpress import AliExpressClient
from app.clients.awin import AwinClient
from app.clients.shopee_affiliate import ShopeeAffiliateClient
from app.collector_runner import SOURCE_AWIN, collect_from_all_sources
from app.collectors.aliexpress import AliExpressCollector
from app.collectors.aliexpress_api_coupon_campaigns import (
    AliExpressApiCouponCampaignCollector,
)
from app.collectors.aliexpress_featured_promotions import (
    AliExpressFeaturedPromotionsCollector,
)
from app.collectors.aliexpress_hot_products import AliExpressHotProductsCollector
from app.collectors.awin import AwinCollector
from app.collectors.coupon_campaign_base import CouponCampaignCollector
from app.collectors.manual_coupon_campaigns import ManualCouponCampaignCollector
from app.collectors.mock import MockCollector
from app.collectors.shopee import ShopeeCollector
from app.coupon_config import (
    load_coupon_config,
    load_manual_coupon_campaigns,
    load_manual_product_coupon_bindings,
)
from app.coupon_formatter import format_coupon_campaign
from app.coupon_identity import build_publication_key
from app.coupon_lifecycle import (
    DEFAULT_TIMEZONE,
    is_campaign_expired,
    is_campaign_scheduled,
    now_in_timezone,
)
from app.coupon_persistence import CouponCampaignPersistence
from app.coupon_pipeline import attach_product_coupons
from app.coupon_repost_policy import build_campaign_snapshot, should_send_campaign
from app.formatter import format_promotion
from app.logger import configure_logging
from app.message_actions import get_message_actions
from app.models import CouponCampaign, FormattedMessage, Promotion
from app.normalizer import normalize
from app.offer_selection import (
    select_diversified_offers,
    select_offer_candidates,
)
from app.persistence import (
    JsonPersistence,
    migrate_legacy_sent_promotions,
    product_persistence_path,
)
from app.product_identity import build_offer_key, build_product_key, build_product_price_key
from app.promotion_merger import merge_duplicate_promotions
from app.promotion_quality import apply_promotion_quality, is_publishable_promotion
from app.promotion_rules import apply_promotion_rules, load_promotion_rules
from app.repost_policy import (
    build_sent_snapshot,
    should_send_promotion,
    titles_are_equivalent,
)
from app.router import route_campaign_offer, route_promotion
from app.scheduler import run_worker
from app.sender.telegram import TelegramSender
from app.settings import Settings
from app.sku_grouping import explode_sku_group_promotion, group_sku_promotions
from app.sku_models import SkuMetrics
from app.sku_pipeline import (
    enrich_finalists_with_delivery,
    expand_promotions_with_skus,
    log_sku_metrics,
)

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _count_by_collector_type(raw_items: list[dict]) -> dict:
    counts = {
        "featured_promotions": 0,
        "hot_products": 0,
        "product_search": 0,
    }
    for item in raw_items:
        collector_type = (item.get("metadata") or {}).get("collector_type")
        if collector_type in counts:
            counts[collector_type] += 1
    return counts


_ALIEXPRESS_SECTIONS = (
    "aliexpress",
    "aliexpress_hot_products",
    "aliexpress_featured_promotions",
)


def _build_aliexpress_client(settings: Settings) -> AliExpressClient | None:
    if not settings.aliexpress_app_key or not settings.aliexpress_app_secret:
        logger.error(
            "AliExpress habilitado, mas ALIEXPRESS_APP_KEY/ALIEXPRESS_APP_SECRET "
            "não estão configurados. Fontes AliExpress ignoradas."
        )
        return None

    return AliExpressClient(
        app_key=settings.aliexpress_app_key,
        app_secret=settings.aliexpress_app_secret,
        endpoint=settings.aliexpress_api_endpoint,
        sign_method=settings.aliexpress_sign_method,
        tracking_id=settings.aliexpress_tracking_id,
        target_currency=settings.aliexpress_target_currency,
        target_language=settings.aliexpress_target_language,
        ship_to_country=settings.aliexpress_ship_to_country,
        debug_responses=settings.app_env == "local",
    )


def _build_aliexpress_collectors(
    sources_config: dict,
    settings: Settings,
    client: AliExpressClient | None = None,
) -> list:
    if not any(
        sources_config.get(section, {}).get("enabled", False)
        for section in _ALIEXPRESS_SECTIONS
    ):
        return []

    resolved_client = client or _build_aliexpress_client(settings)
    if resolved_client is None:
        return []

    collectors = []

    featured_config = sources_config.get("aliexpress_featured_promotions", {})
    if featured_config.get("enabled", False):
        collectors.append(
            AliExpressFeaturedPromotionsCollector(
                client=resolved_client, source_config=featured_config
            )
        )

    hot_config = sources_config.get("aliexpress_hot_products", {})
    if hot_config.get("enabled", False):
        collectors.append(
            AliExpressHotProductsCollector(
                client=resolved_client, source_config=hot_config
            )
        )

    product_search_config = sources_config.get("aliexpress", {})
    if product_search_config.get("enabled", False):
        collectors.append(
            AliExpressCollector(
                client=resolved_client, source_config=product_search_config
            )
        )

    return collectors


def _build_shopee_client(settings: Settings) -> ShopeeAffiliateClient | None:
    if not settings.shopee_app_id or not settings.shopee_app_secret:
        logger.error(
            "Shopee habilitada, mas SHOPEE_APP_ID/SHOPEE_APP_SECRET "
            "não estão configurados. Fonte Shopee ignorada."
        )
        return None

    logger.info(
        "Shopee client ok (app_id=%s... url=%s page_limit=%s max_pages=%s)",
        settings.shopee_app_id[:4],
        settings.shopee_api_url,
        settings.shopee_page_limit,
        settings.shopee_max_pages,
    )
    return ShopeeAffiliateClient(
        app_id=settings.shopee_app_id,
        app_secret=settings.shopee_app_secret,
        api_url=settings.shopee_api_url,
        timeout=settings.shopee_request_timeout,
        page_limit=settings.shopee_page_limit,
    )


def _build_awin_client(settings: Settings) -> AwinClient | None:
    if not settings.awin_oauth2_token or not settings.awin_publisher_id:
        logger.error(
            "Awin habilitada, mas AWIN_OAUTH2_TOKEN/AWIN_PUBLISHER_ID "
            "não estão configurados. Fonte Awin ignorada."
        )
        return None

    logger.info(
        "Awin client ok (publisher_id=%s)",
        settings.awin_publisher_id,
    )
    return AwinClient(
        oauth2_token=settings.awin_oauth2_token,
        publisher_id=settings.awin_publisher_id,
    )


def _build_collectors(
    sources_config: dict,
    settings: Settings,
    aliexpress_client: AliExpressClient | None = None,
    now=None,
) -> list:
    collectors = []

    mock_config = sources_config.get("mock", {})
    if mock_config.get("enabled", False):
        collectors.append(MockCollector(max_items=mock_config.get("max_items_per_run", 10)))

    shopee_config = sources_config.get("shopee", {})
    if shopee_config.get("enabled", False):
        client = _build_shopee_client(settings)
        if client is not None:
            collectors.append(
                ShopeeCollector(
                    client=client,
                    keywords=shopee_config.get("keywords", []),
                    max_items_per_run=shopee_config.get("max_items_per_run", 20),
                    page_limit=settings.shopee_page_limit,
                    max_pages=settings.shopee_max_pages,
                )
            )

    collectors.extend(
        _build_aliexpress_collectors(sources_config, settings, aliexpress_client)
    )

    awin_config = sources_config.get("awin", {})
    if awin_config.get("enabled", False):
        awin_client = _build_awin_client(settings)
        if awin_client is not None:
            collectors.append(
                AwinCollector(
                    client=awin_client,
                    advertisers=load_awin_advertisers(awin_config),
                    membership=awin_config.get("membership", "joined"),
                    region_codes=awin_config.get("region_codes", ["BR"]),
                    status=awin_config.get("status", "active"),
                    offer_type=awin_config.get("type", "all"),
                    page_size=int(awin_config.get("page_size", 200)),
                    max_items_per_run=awin_config.get("max_items_per_run"),
                    product_feed_url=settings.awin_product_feed_url,
                    feed_locale=settings.awin_feed_locale,
                    now=now,
                )
            )

    return collectors


def _build_sender(settings: Settings) -> TelegramSender:
    return TelegramSender(
        bot_token=settings.telegram_bot_token,
        dry_run=settings.telegram_dry_run,
        min_interval_seconds=settings.telegram_send_interval_seconds,
    )


def send_formatted_message(
    formatted: FormattedMessage,
    destinations: list[dict],
    senders: dict,
) -> bool:
    actions = get_message_actions(formatted)
    success = False

    for destination in destinations:
        sender = senders.get(destination["channel"])
        if sender is None:
            continue

        result = sender.send(
            chat_id=destination["chat_id"],
            message=formatted.text,
            image_url=formatted.image_url,
            actions=actions,
        )
        if result.success:
            success = True
        else:
            logger.error("Falha ao enviar para destino: %s", result.error)

    return success


def _filter_sku_group_variations(
    promotions: list[Promotion],
    promotion_rules: dict,
    absolute_tolerance: Decimal = Decimal("1.00"),
    percent_tolerance: Decimal = Decimal("0.02"),
) -> list[Promotion]:
    filtered: list[Promotion] = []
    for promotion in promotions:
        if not isinstance(
            (promotion.metadata or {}).get("sku_offer_group"), dict
        ):
            filtered.append(promotion)
            continue

        approved_variations: list[Promotion] = []
        for variation in explode_sku_group_promotion(promotion):
            apply_promotion_quality(variation)
            if not is_publishable_promotion(variation):
                logger.info(
                    "SKU rejeitada por qualidade: product_id=%s sku_id=%s",
                    variation.metadata.get("parent_product_id"),
                    variation.metadata.get("sku_variant", {}).get("sku_id"),
                )
                continue
            approved, reasons = apply_promotion_rules(
                variation, promotion_rules
            )
            if not approved:
                logger.info(
                    "SKU rejeitada por regras: product_id=%s sku_id=%s reasons=%s",
                    variation.metadata.get("parent_product_id"),
                    variation.metadata.get("sku_variant", {}).get("sku_id"),
                    reasons,
                )
                continue
            approved_variations.append(variation)

        if approved_variations:
            filtered.extend(
                group_sku_promotions(
                    approved_variations,
                    absolute_tolerance=absolute_tolerance,
                    percent_tolerance=percent_tolerance,
                )
            )
    return filtered


def _run_product_pipeline(
    settings: Settings,
    sources_config: dict,
    categories_config: dict,
    channels_config: dict,
    senders: dict,
    data_dir: Path,
    bindings: dict,
    now,
    raw_items: list[dict],
    aliexpress_client: AliExpressClient | None = None,
) -> None:
    promotions = normalize(raw_items)
    normalized_count = len(promotions)
    sku_config = sources_config.get("aliexpress_sku_dimension", {})
    sku_metrics = SkuMetrics()
    promotions = expand_promotions_with_skus(
        promotions,
        client=aliexpress_client,
        enabled=sku_config.get("enabled", False),
        max_queries=sku_config.get("max_queries_per_run", 20),
        metrics=sku_metrics,
    )

    products_with_coupons, coupons_attached = attach_product_coupons(
        promotions,
        bindings,
        now,
        aliexpress_client=aliexpress_client,
        max_product_details=sources_config.get(
            "aliexpress_coupon_campaigns", {}
        ).get("max_product_details_per_run", 5),
    )
    absolute_tolerance = Decimal(
        str(sku_config.get("price_tolerance_absolute", "1.00"))
    )
    percent_tolerance = Decimal(
        str(sku_config.get("price_tolerance_percent", "0.02"))
    )
    promotions = group_sku_promotions(
        promotions,
        absolute_tolerance=absolute_tolerance,
        percent_tolerance=percent_tolerance,
        metrics=sku_metrics,
    )
    promotion_rules = load_promotion_rules(settings.config_dir)
    for promotion in promotions:
        resolve_category(promotion, categories_config)
    promotions = _filter_sku_group_variations(
        promotions,
        promotion_rules,
        absolute_tolerance,
        percent_tolerance,
    )

    for promotion in promotions:
        resolve_category(promotion, categories_config)
        build_product_key(promotion)
        build_offer_key(promotion)
        build_product_price_key(promotion)
        apply_promotion_quality(promotion)

    quality_promotions = [p for p in promotions if is_publishable_promotion(p)]
    quality_rejected = len(promotions) - len(quality_promotions)

    rules_approved: list = []
    rules_rejected = 0
    for promotion in quality_promotions:
        approved, reasons = apply_promotion_rules(promotion, promotion_rules)
        if approved:
            rules_approved.append(promotion)
            continue
        rules_rejected += 1
        logger.info(
            'Promotion rejected by rules: title="%s" reasons=%s',
            (promotion.title or "")[:80],
            reasons,
        )

    merged_promotions = merge_duplicate_promotions(rules_approved)
    merged_duplicates = len(rules_approved) - len(merged_promotions)

    parent_group_count = len(
        {build_product_key(promotion) for promotion in merged_promotions}
    )
    selected_offers = select_offer_candidates(merged_promotions)
    sku_metrics.final_sku_offers = sum(
        1
        for offer in selected_offers
        if isinstance((offer.metadata or {}).get("sku_offer_group"), dict)
    )

    persistences: dict[str, JsonPersistence] = {}
    snapshots_by_source: dict[str, list] = {}

    def _snapshots_for(source: str) -> tuple[JsonPersistence, list]:
        if source not in persistences:
            persistence = JsonPersistence(
                str(product_persistence_path(data_dir, source)),
                retain_hours=settings.repost_window_hours,
            )
            persistences[source] = persistence
            snapshots_by_source[source] = persistence.load_snapshots()
        return persistences[source], snapshots_by_source[source]

    allowed_offers = []
    for offer in selected_offers:
        _, snapshots = _snapshots_for(offer.source)
        if not should_send_promotion(offer, snapshots, settings.repost_window_hours):
            continue
        duplicate_in_run = False
        for accepted in allowed_offers:
            if accepted.source != offer.source:
                continue
            if titles_are_equivalent(offer.title, accepted.title):
                duplicate_in_run = True
                break
        if duplicate_in_run:
            continue
        allowed_offers.append(offer)

    offers_to_send = select_diversified_offers(
        allowed_offers,
        max_total=None,
        max_per_parent=sku_config.get(
            "max_offers_per_parent_per_run", 1
        ),
    )
    by_source: dict[str, int] = {}
    for offer in offers_to_send:
        by_source[offer.source] = by_source.get(offer.source, 0) + 1
    logger.info(
        "Ofertas para envio: total=%s por_fonte=%s (sem teto global MAX_PRODUCTS_PER_RUN)",
        len(offers_to_send),
        by_source,
    )

    sent_count = 0
    unrouted_count = 0
    send_failed_count = 0
    routed_offers: list[tuple[Promotion, list[dict]]] = []

    for promotion in offers_to_send:
        category = promotion.resolved_category or "geral"
        destinations = route_promotion(category, channels_config)
        if not destinations:
            unrouted_count += 1
            continue
        routed_offers.append((promotion, destinations))

    enrich_finalists_with_delivery(
        [promotion for promotion, _ in routed_offers],
        client=aliexpress_client,
        enabled=sku_config.get("enabled", False),
        display_delivery=sku_config.get("display_delivery", False),
        metrics=sku_metrics,
        max_queries=sku_config.get("max_delivery_queries_per_run", 10),
    )

    for promotion, destinations in routed_offers:
        formatted = format_promotion(promotion, now)
        if send_formatted_message(formatted, destinations, senders):
            snapshot = build_sent_snapshot(promotion)
            persistence, snapshots = _snapshots_for(promotion.source)
            persistence.add_snapshot(snapshot)
            snapshots.append(snapshot)
            sent_count += 1
        else:
            send_failed_count += 1

    blocked_count = len(selected_offers) - len(allowed_offers)
    collected_by_type = _count_by_collector_type(raw_items)

    logger.info(
        "Featured products collected: %s", collected_by_type["featured_promotions"]
    )
    logger.info("Hot products collected: %s", collected_by_type["hot_products"])
    logger.info("Product search collected: %s", collected_by_type["product_search"])
    logger.info("Products collected: %s", len(raw_items))
    logger.info("Normalized: %s", normalized_count)
    logger.info("Quality approved: %s", len(quality_promotions))
    logger.info("Quality rejected: %s", quality_rejected)
    logger.info("Rules approved: %s", len(rules_approved))
    logger.info("Rules rejected: %s", rules_rejected)
    logger.info("Merged duplicates: %s", merged_duplicates)
    logger.info("Products with coupons: %s", products_with_coupons)
    logger.info("Coupons attached to products: %s", coupons_attached)
    logger.info("Groups: %s", parent_group_count)
    logger.info("Selected offers: %s", len(selected_offers))
    logger.info("Allowed to send: %s", len(allowed_offers))
    logger.info("Queued to send: %s", len(offers_to_send))
    logger.info("Sent: %s", sent_count)
    parent_deferred = len(allowed_offers) - len(offers_to_send)
    if parent_deferred > 0:
        logger.info(
            "Deferred by max_per_parent only: %s",
            parent_deferred,
        )
    logger.info("Blocked by repost policy: %s", blocked_count)
    logger.info("Without destination: %s", unrouted_count)
    logger.info("Send failures: %s", send_failed_count)
    if sku_config.get("enabled", False):
        log_sku_metrics(sku_metrics)


def _dedupe_campaigns(campaigns: list[CouponCampaign]) -> list[CouponCampaign]:
    unique: list[CouponCampaign] = []
    seen: set[str] = set()
    for campaign in campaigns:
        key = build_publication_key(campaign)
        if key in seen:
            continue
        seen.add(key)
        unique.append(campaign)
    return unique


def _build_coupon_campaign_collectors(
    settings: Settings,
    sources_config: dict,
    manual_campaigns: list[CouponCampaign],
    timezone_name: str,
    aliexpress_client: AliExpressClient | None,
) -> list[CouponCampaignCollector]:
    collectors: list[CouponCampaignCollector] = [
        ManualCouponCampaignCollector(manual_campaigns, timezone_name)
    ]

    api_config = sources_config.get("aliexpress_coupon_campaigns", {})
    featured_config = sources_config.get("aliexpress_featured_promotions", {})
    enabled = api_config.get("enabled", featured_config.get("enabled", False))

    if enabled and aliexpress_client is not None:
        merged_config = {
            "max_campaigns_per_run": api_config.get(
                "max_campaigns_per_run",
                featured_config.get("max_campaigns_per_run", 3),
            ),
            "max_items_per_campaign": api_config.get(
                "max_items_per_campaign",
                featured_config.get("max_items_per_campaign", 10),
            ),
            "max_product_details_per_run": api_config.get(
                "max_product_details_per_run", 5
            ),
            "allowed_campaigns": api_config.get(
                "allowed_campaigns", featured_config.get("allowed_campaigns", [])
            ),
            "blocked_campaigns": api_config.get(
                "blocked_campaigns", featured_config.get("blocked_campaigns", [])
            ),
            "preferred_campaign_patterns": api_config.get(
                "preferred_campaign_patterns",
                featured_config.get("preferred_campaign_patterns", []),
            ),
            "blocked_campaign_patterns": api_config.get(
                "blocked_campaign_patterns",
                featured_config.get("blocked_campaign_patterns", []),
            ),
        }
        collectors.append(
            AliExpressApiCouponCampaignCollector(
                client=aliexpress_client,
                source_config=merged_config,
                timezone_name=timezone_name,
            )
        )

    return collectors


def _run_coupon_campaign_pipeline(
    settings: Settings,
    channels_config: dict,
    senders: dict,
    collectors: list[CouponCampaignCollector],
    timezone_name: str,
    data_dir: Path,
    now,
) -> None:
    campaigns: list[CouponCampaign] = []
    for collector in collectors:
        try:
            campaigns.extend(collector.collect(now))
        except Exception as exc:
            logger.error(
                "Collector de campanha %s falhou e foi ignorado: %s",
                type(collector).__name__,
                exc,
            )

    campaigns = _dedupe_campaigns(campaigns)

    scheduled = [c for c in campaigns if is_campaign_scheduled(c, now)]
    active = [c for c in campaigns if not is_campaign_scheduled(c, now)]
    expired = sum(1 for c in campaigns if is_campaign_expired(c, now))

    persistence = CouponCampaignPersistence(
        str(data_dir / "sent_coupon_campaigns.json"),
        retain_hours=settings.coupon_repost_window_hours,
    )
    snapshots = persistence.load_snapshots()

    allowed = [
        campaign
        for campaign in campaigns
        if should_send_campaign(
            campaign, snapshots, now, settings.coupon_repost_window_hours
        )
    ]

    sent = 0
    skipped = 0

    for campaign in allowed:
        category = campaign.category or "geral"
        destinations = route_promotion(category, channels_config)
        if not destinations:
            skipped += 1
            continue

        formatted = format_coupon_campaign(campaign, now)
        if send_formatted_message(formatted, destinations, senders):
            snapshot = build_campaign_snapshot(
                campaign, [d["chat_id"] for d in destinations], now
            )
            persistence.add_snapshot(snapshot)
            snapshots.append(snapshot)
            sent += 1
        else:
            skipped += 1

    logger.info("Coupon campaigns collected: %s", len(campaigns))
    logger.info("Coupon campaigns active: %s", len(active))
    logger.info("Coupon campaigns scheduled: %s", len(scheduled))
    logger.info("Coupon campaigns expired: %s", expired)
    logger.info("Coupon campaigns allowed: %s", len(allowed))
    logger.info("Coupon campaigns sent: %s", sent)
    logger.info("Coupon campaigns skipped: %s", skipped)


def _run_awin_pipeline(
    settings: Settings,
    categories_config: dict,
    channels_config: dict,
    senders: dict,
    data_dir: Path,
    raw_items: list[dict],
    now,
) -> None:
    offers = [campaign_offer_from_dict(item) for item in raw_items]
    for offer in offers:
        resolve_campaign_offer_category(offer, categories_config)

    persistence = AwinOfferPersistence(
        str(data_dir / "sent_awin_offers.json"),
        retain_hours=settings.repost_window_hours,
    )
    snapshots = persistence.load_snapshots()

    sent = 0
    skipped_repost = 0
    send_failures = 0
    unrouted = 0

    for offer in offers:
        category = offer.resolved_category or "geral"
        destinations = route_campaign_offer(offer.kind, category, channels_config)
        if not destinations:
            unrouted += 1
            continue

        formatted = format_campaign_offer(offer)

        for destination in destinations:
            dest_category = destination["category"]
            if not should_send_offer_to_destination(
                offer,
                dest_category,
                snapshots,
                now,
                settings.repost_window_hours,
            ):
                skipped_repost += 1
                continue

            sender = senders.get(destination["channel"])
            if sender is None:
                send_failures += 1
                continue

            actions = get_message_actions(formatted)
            result = sender.send(
                chat_id=destination["chat_id"],
                message=formatted.text,
                image_url=formatted.image_url,
                actions=actions,
            )
            if not result.success:
                send_failures += 1
                logger.error(
                    "Awin send failure offer=%s destination=%s chat_id=%s error=%s",
                    offer.external_id,
                    dest_category,
                    destination.get("chat_id"),
                    result.error,
                )
                continue

            sent += 1
            if result.provider_message_id == "dry-run":
                continue

            snapshot = build_offer_snapshot(offer, dest_category, now)
            persistence.add_snapshot(snapshot)
            snapshots.append(snapshot)

    logger.info("Awin offers collected: %s", len(offers))
    logger.info("Awin offers sent: %s", sent)
    logger.info("Awin offers skipped by antirrepost: %s", skipped_repost)
    logger.info("Awin offers without destination: %s", unrouted)
    logger.info("Awin send failures: %s", send_failures)


def run_once(settings: Settings) -> None:
    config_dir = Path(settings.config_dir)
    data_dir = Path(settings.data_dir)

    sources_config = _load_json(config_dir / "sources.json")
    categories_config = _load_json(config_dir / "categories.json")
    channels_config = _load_json(config_dir / "channels.json")

    coupon_config = load_coupon_config(settings.config_dir)
    timezone_name = coupon_config.get("timezone", DEFAULT_TIMEZONE)
    now = now_in_timezone(timezone_name)
    bindings = load_manual_product_coupon_bindings(coupon_config)
    manual_campaigns = load_manual_coupon_campaigns(coupon_config)

    sender = _build_sender(settings)
    senders = {"telegram": sender}
    migrate_legacy_sent_promotions(data_dir)

    aliexpress_needed = any(
        sources_config.get(section, {}).get("enabled", False)
        for section in (
            "aliexpress",
            "aliexpress_hot_products",
            "aliexpress_featured_promotions",
            "aliexpress_coupon_campaigns",
            "aliexpress_sku_dimension",
        )
    )
    aliexpress_client = (
        _build_aliexpress_client(settings) if aliexpress_needed else None
    )

    collectors = _build_collectors(
        sources_config,
        settings,
        aliexpress_client,
        now=now,
    )
    raw_items = collect_from_all_sources(collectors)
    product_items = [
        item for item in raw_items if item.get("source") != SOURCE_AWIN
    ]
    awin_items = [
        item for item in raw_items if item.get("source") == SOURCE_AWIN
    ]

    _run_product_pipeline(
        settings,
        sources_config,
        categories_config,
        channels_config,
        senders,
        data_dir,
        bindings,
        now,
        product_items,
        aliexpress_client=aliexpress_client,
    )

    _run_awin_pipeline(
        settings,
        categories_config,
        channels_config,
        senders,
        data_dir,
        awin_items,
        now,
    )

    coupon_collectors = _build_coupon_campaign_collectors(
        settings,
        sources_config,
        manual_campaigns,
        timezone_name,
        aliexpress_client,
    )

    _run_coupon_campaign_pipeline(
        settings,
        channels_config,
        senders,
        coupon_collectors,
        timezone_name,
        data_dir,
        now,
    )


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    logger.info("PromoFlash Bot iniciando (env=%s, mode=%s)", settings.app_env, settings.run_mode)
    run_worker(settings)


if __name__ == "__main__":
    main()
