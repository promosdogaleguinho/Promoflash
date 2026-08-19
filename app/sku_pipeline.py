import logging
from dataclasses import replace

from app.clients.aliexpress import AliExpressClient
from app.models import Promotion
from app.sku_evaluation import evaluate_skus
from app.sku_models import SkuApiResult, SkuApiStatus, SkuMetrics, SkuStatus, SkuVariant

logger = logging.getLogger(__name__)

SOURCE_ALIEXPRESS = "aliexpress"


def _serialize_sku(sku: SkuVariant) -> dict:
    return {
        "sku_id": sku.sku_id,
        "properties": [
            {"name": property_item.name, "value": property_item.value}
            for property_item in sku.properties
        ],
        "variation_label": sku.variation_label,
        "material_signature": sku.material_signature,
        "cosmetic_label": sku.cosmetic_label,
        "grouping_dimension": sku.grouping_dimension,
        "original_price": str(sku.original_price)
        if sku.original_price is not None
        else None,
        "sale_price": str(sku.sale_price) if sku.sale_price is not None else None,
        "effective_price": str(sku.effective_price)
        if sku.effective_price is not None
        else None,
        "discount_rate": str(sku.discount_rate)
        if sku.discount_rate is not None
        else None,
        "currency": sku.currency,
        "image_url": sku.image_url,
        "affiliate_url": sku.affiliate_url,
        "shipping_fee": str(sku.shipping_fee)
        if sku.shipping_fee is not None
        else None,
        "delivery_days": sku.delivery_days,
        "min_delivery_days": sku.min_delivery_days,
        "max_delivery_days": sku.max_delivery_days,
        "ship_from_country": sku.ship_from_country,
        "availability_status": sku.availability_status,
        "sku_status": sku.sku_status.value,
        "rejection_reason": sku.rejection_reason,
    }


def _update_query_metrics(result: SkuApiResult, metrics: SkuMetrics) -> None:
    metrics.products_queried += 1
    if result.status == SkuApiStatus.SUCCESS:
        metrics.successful_queries += 1
    elif result.status == SkuApiStatus.NOT_FOUND:
        metrics.responses_405 += 1
    elif result.status == SkuApiStatus.ERROR:
        metrics.other_errors += 1

    count = len(result.skus)
    metrics.total_skus_returned += count
    metrics.parsed_properties += sum(len(sku.properties) for sku in result.skus)
    metrics.invalid_properties += sum(
        1 for sku in result.skus if sku.rejection_reason == "sku_properties_invalid"
    )
    if count == 0:
        metrics.products_without_sku_data += 1
    elif count == 1:
        metrics.products_with_one_sku += 1
    else:
        metrics.products_with_multiple_skus += 1
    if result.coverage_may_be_incomplete:
        metrics.responses_with_20_skus += 1


def _aggregate_fallback_is_safe(promotion: Promotion) -> bool:
    return bool((promotion.metadata or {}).get("sku_aggregate_fallback_safe"))


def _fallback_or_block(
    promotion: Promotion,
    reason: str,
    metrics: SkuMetrics,
) -> list[Promotion]:
    if _aggregate_fallback_is_safe(promotion):
        metadata = dict(promotion.metadata)
        metadata["sku_fallback_reason"] = reason
        metrics.aggregate_fallbacks_kept += 1
        logger.info(
            "Produto agregado mantido por fallback explícito: product_id=%s reason=%s",
            promotion.external_id,
            reason,
        )
        return [replace(promotion, metadata=metadata)]

    metrics.aggregate_fallbacks_blocked += 1
    logger.info(
        "Produto agregado bloqueado por risco de preço enganoso: "
        "product_id=%s reason=%s",
        promotion.external_id,
        reason,
    )
    return []


def _keep_without_sku_enrichment(
    promotion: Promotion,
    reason: str,
    metrics: SkuMetrics,
) -> Promotion:
    metadata = dict(promotion.metadata)
    metadata["sku_enrichment_skipped_reason"] = reason
    metrics.aggregate_fallbacks_kept += 1
    return replace(promotion, metadata=metadata)


def _promotion_from_sku(
    promotion: Promotion,
    sku: SkuVariant,
    coverage_may_be_incomplete: bool,
) -> Promotion:
    metadata = dict(promotion.metadata)
    metadata["parent_product_id"] = promotion.external_id
    metadata["sku_variant"] = _serialize_sku(sku)
    metadata["sku_coverage_may_be_incomplete"] = coverage_may_be_incomplete
    effective_price = sku.effective_price
    return replace(
        promotion,
        price=float(effective_price) if effective_price is not None else None,
        final_price=float(effective_price) if effective_price is not None else None,
        old_price=float(sku.original_price)
        if sku.original_price is not None
        and effective_price is not None
        and sku.original_price > effective_price
        else None,
        discount_percentage=float(sku.discount_rate)
        if sku.discount_rate is not None
        else None,
        affiliate_url=sku.affiliate_url or promotion.affiliate_url,
        image_url=sku.image_url or promotion.image_url,
        metadata=metadata,
    )


def expand_promotions_with_skus(
    promotions: list[Promotion],
    client: AliExpressClient | None,
    enabled: bool,
    max_queries: int,
    metrics: SkuMetrics,
) -> list[Promotion]:
    if not enabled or client is None or max_queries <= 0:
        return promotions

    expanded: list[Promotion] = []
    query_count = 0
    results_by_product: dict[str, SkuApiResult] = {}
    for promotion in promotions:
        if promotion.source != SOURCE_ALIEXPRESS:
            expanded.append(promotion)
            continue
        product_id = promotion.external_id
        cached_result = results_by_product.get(product_id)
        is_cached_result = cached_result is not None
        if cached_result is None and query_count >= max_queries:
            expanded.append(
                _keep_without_sku_enrichment(
                    promotion,
                    "limite_de_consultas",
                    metrics,
                )
            )
            continue

        if cached_result is None:
            query_count += 1
            result = client.product_sku_detail_get(
                product_id=product_id,
                need_deliver_info=False,
            )
            results_by_product[product_id] = result
            _update_query_metrics(result, metrics)
        else:
            result = cached_result

        if result.status != SkuApiStatus.SUCCESS or not result.skus:
            expanded.append(
                _keep_without_sku_enrichment(
                    promotion,
                    f"sku_api_{result.status.value}",
                    metrics,
                )
            )
            continue

        evaluated = evaluate_skus(
            result.skus,
            promotion.title,
            None if is_cached_result else metrics,
        )
        for sku in evaluated:
            if sku.sku_status == SkuStatus.RESOLVED:
                continue
            logger.info(
                "SKU não gerou oferta específica: product_id=%s sku_id=%s "
                "status=%s reason=%s",
                product_id,
                sku.sku_id,
                sku.sku_status.value,
                sku.rejection_reason,
            )
        trusted = [
            sku for sku in evaluated if sku.sku_status == SkuStatus.RESOLVED
        ]
        if not trusted:
            metrics.products_without_trusted_skus += 1
            expanded.extend(
                _fallback_or_block(promotion, "nenhuma_sku_confiavel", metrics)
            )
            continue

        expanded.extend(
            _promotion_from_sku(
                promotion,
                sku,
                result.coverage_may_be_incomplete,
            )
            for sku in trusted
        )
    return expanded


def _delivery_by_sku_id(result: SkuApiResult) -> dict[str, SkuVariant]:
    return {sku.sku_id: sku for sku in result.skus if sku.sku_id}


def enrich_finalists_with_delivery(
    promotions: list[Promotion],
    client: AliExpressClient | None,
    enabled: bool,
    display_delivery: bool,
    metrics: SkuMetrics,
    max_queries: int | None = None,
) -> None:
    if not enabled or client is None:
        return

    by_product: dict[str, list[Promotion]] = {}
    for promotion in promotions:
        group = promotion.metadata.get("sku_offer_group")
        product_id = promotion.metadata.get("parent_product_id")
        if not isinstance(group, dict) or not product_id:
            continue
        by_product.setdefault(str(product_id), []).append(promotion)

    for product_id, product_promotions in by_product.items():
        if max_queries is not None and metrics.delivery_queries >= max_queries:
            logger.info(
                "Enriquecimento de entrega adiado por limite de consultas: "
                "product_id=%s",
                product_id,
            )
            continue
        sku_ids = sorted(
            {
                str(sku_id)
                for promotion in product_promotions
                for sku_id in promotion.metadata["sku_offer_group"].get(
                    "sku_ids", []
                )
            }
        )
        metrics.delivery_queries += 1
        result = client.product_sku_detail_get(
            product_id=product_id,
            need_deliver_info=True,
            sku_ids=sku_ids,
        )
        if result.status != SkuApiStatus.SUCCESS:
            metrics.delivery_failures += 1
            logger.warning(
                "Enriquecimento de entrega falhou sem bloquear oferta: "
                "product_id=%s status=%s",
                product_id,
                result.status.value,
            )
            continue

        metrics.successful_delivery_queries += 1
        delivery_by_sku = _delivery_by_sku_id(result)
        for promotion in product_promotions:
            metadata = dict(promotion.metadata)
            group = dict(metadata["sku_offer_group"])
            variations = []
            for variation in group.get("variations", []):
                updated = dict(variation)
                sku_id = str(updated.get("sku_id") or "")
                delivery_sku = delivery_by_sku.get(sku_id)
                if delivery_sku is None:
                    metrics.missing_skus_in_delivery_response += 1
                    logger.info(
                        "SKU finalista ausente na resposta de entrega: "
                        "product_id=%s sku_id=%s",
                        product_id,
                        sku_id,
                    )
                else:
                    updated.update(
                        {
                            "shipping_fee": str(delivery_sku.shipping_fee)
                            if delivery_sku.shipping_fee is not None
                            else None,
                            "delivery_days": delivery_sku.delivery_days,
                            "min_delivery_days": delivery_sku.min_delivery_days,
                            "max_delivery_days": delivery_sku.max_delivery_days,
                            "ship_from_country": delivery_sku.ship_from_country,
                        }
                    )
                variations.append(updated)
            group["variations"] = variations
            metadata["sku_offer_group"] = group
            metadata["display_sku_delivery"] = display_delivery
            promotion.metadata = metadata


def log_sku_metrics(metrics: SkuMetrics) -> None:
    for name, value in vars(metrics).items():
        logger.info("SKU metric %s=%s", name, value)
