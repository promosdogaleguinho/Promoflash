from decimal import Decimal
from unittest.mock import MagicMock

from app.formatter import format_promotion
from app.main import _filter_sku_group_variations
from app.models import Promotion
from app.sku_grouping import group_sku_promotions
from app.sku_models import (
    SkuApiResult,
    SkuApiStatus,
    SkuMetrics,
    SkuProperty,
    SkuVariant,
)
from app.sku_pipeline import (
    enrich_finalists_with_delivery,
    expand_promotions_with_skus,
)


def _promotion(safe_fallback: bool = False) -> Promotion:
    return Promotion(
        external_id="p1",
        source="aliexpress",
        title="Smartphone principal",
        url="https://example.test/p1",
        affiliate_url="https://example.test/aff/p1",
        price=100,
        final_price=100,
        metadata={"sku_aggregate_fallback_safe": safe_fallback},
    )


def _sku(
    sku_id: str = "s1",
    price: str | None = "80",
    value: str = "Black",
    shipping: str | None = None,
) -> SkuVariant:
    return SkuVariant(
        sku_id=sku_id,
        properties=[SkuProperty(name="cor", value=value)],
        variation_label=value,
        original_price=Decimal("100"),
        sale_price=Decimal(price) if price is not None else None,
        effective_price=Decimal(price) if price is not None else None,
        discount_rate=Decimal("20"),
        currency="BRL",
        image_url=f"https://example.test/{sku_id}.jpg",
        affiliate_url=f"https://example.test/p1?sku={sku_id}",
        shipping_fee=Decimal(shipping) if shipping is not None else None,
    )


def _client_result(result: SkuApiResult):
    client = MagicMock()
    client.product_sku_detail_get.return_value = result
    return client


def test_single_sku_expands_to_normalized_offer():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku(value="Black")],
    )
    metrics = SkuMetrics()
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, metrics
    )
    assert len(expanded) == 1
    normalized = expanded[0].metadata["sku_variant"]
    assert normalized["sku_id"] == "s1"
    assert normalized["variation_label"] == "Black"
    assert normalized["cosmetic_label"] == "Preto"
    assert normalized["effective_price"] == "80"
    assert normalized["availability_status"] == "unknown"
    assert normalized["sku_status"] == "resolved"


def test_multiple_skus_expand_without_selecting_only_cheapest():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku("s1", "80", "Black"), _sku("s2", "90", "White")],
    )
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, SkuMetrics()
    )
    assert [item.final_price for item in expanded] == [80.0, 90.0]


def test_405_keeps_aggregate_offer_as_non_blocking_fallback():
    result = SkuApiResult(status=SkuApiStatus.NOT_FOUND, product_id="p1")
    client = _client_result(result)
    metrics = SkuMetrics()
    kept = expand_promotions_with_skus(
        [_promotion(False)], client, True, 5, metrics
    )
    assert len(kept) == 1
    assert (
        kept[0].metadata["sku_enrichment_skipped_reason"]
        == "sku_api_not_found"
    )


def test_query_limit_keeps_remaining_aggregate_offers():
    first = _promotion()
    second = _promotion()
    second.external_id = "p2"
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku()],
    )
    expanded = expand_promotions_with_skus(
        [first, second],
        _client_result(result),
        True,
        1,
        SkuMetrics(),
    )
    remaining = next(item for item in expanded if item.external_id == "p2")
    assert remaining.metadata["sku_enrichment_skipped_reason"] == "limite_de_consultas"


def test_no_trusted_sku_does_not_fall_back_automatically():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku(price=None)],
    )
    metrics = SkuMetrics()
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, metrics
    )
    assert expanded == []
    assert metrics.products_without_trusted_skus == 1
    assert metrics.aggregate_fallbacks_blocked == 1


def test_only_valid_sku_generates_offer_when_another_has_no_price():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku("valid", "80", "Black"), _sku("invalid", None, "White")],
    )
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, SkuMetrics()
    )
    assert len(expanded) == 1
    assert expanded[0].metadata["sku_variant"]["sku_id"] == "valid"


def test_suspicious_accessory_is_not_published_as_specific_offer():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku(value="Case only")],
    )
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, SkuMetrics()
    )
    assert expanded == []


def test_disabled_integration_preserves_original_product_without_call():
    client = MagicMock()
    promotion = _promotion()
    expanded = expand_promotions_with_skus(
        [promotion], client, False, 5, SkuMetrics()
    )
    assert expanded == [promotion]
    client.product_sku_detail_get.assert_not_called()


def _final_groups() -> list[Promotion]:
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[
            _sku("pro-black", "53.69", "GM2 Pro Black"),
            _sku("pro-white", "53.89", "GM2 Pro White"),
            _sku("plus-black", "57.39", "GM2 PLUS Black"),
            _sku("plus-white", "57.29", "GM2 PLUS White"),
        ],
    )
    expanded = expand_promotions_with_skus(
        [_promotion()], _client_result(result), True, 5, SkuMetrics()
    )
    return group_sku_promotions(expanded)


def test_delivery_is_queried_once_per_finalist_product_not_per_group():
    groups = _final_groups()
    delivery_result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[
            _sku("pro-black", "53.69", "GM2 Pro Black", "24"),
            _sku("pro-white", "53.89", "GM2 Pro White", "24"),
            _sku("plus-black", "57.39", "GM2 PLUS Black", "24"),
            _sku("plus-white", "57.29", "GM2 PLUS White", "24"),
        ],
    )
    client = _client_result(delivery_result)
    metrics = SkuMetrics()
    enrich_finalists_with_delivery(groups, client, True, False, metrics)
    client.product_sku_detail_get.assert_called_once()
    kwargs = client.product_sku_detail_get.call_args.kwargs
    assert kwargs["need_deliver_info"] is True
    assert set(kwargs["sku_ids"]) == {
        "pro-black",
        "pro-white",
        "plus-black",
        "plus-white",
    }
    assert metrics.successful_delivery_queries == 1


def test_each_sku_passes_promotion_rules_individually():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[
            _sku("approved", "99", "Black"),
            _sku("rejected", "100.50", "White"),
        ],
    )
    base = _promotion()
    base.is_official_campaign = True
    expanded = expand_promotions_with_skus(
        [base], _client_result(result), True, 5, SkuMetrics()
    )
    grouped = group_sku_promotions(expanded)
    filtered = _filter_sku_group_variations(
        grouped,
        {"global": {"max_price": 100}, "sources": {}, "categories": {}},
    )
    assert len(filtered) == 1
    assert filtered[0].metadata["sku_offer_group"]["sku_ids"] == ["approved"]


def test_filter_group_variations_preserves_configured_tolerance():
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS,
        product_id="p1",
        skus=[_sku("first", "80", "Black"), _sku("second", "85", "White")],
    )
    expanded = expand_promotions_with_skus(
        [_promotion()],
        _client_result(result),
        True,
        5,
        SkuMetrics(),
    )
    grouped = group_sku_promotions(
        expanded,
        absolute_tolerance=Decimal("10"),
        percent_tolerance=Decimal("0"),
    )
    filtered = _filter_sku_group_variations(
        grouped,
        {"global": {"max_price": 100}, "sources": {}, "categories": {}},
        Decimal("10"),
        Decimal("0"),
    )
    assert len(filtered) == 1
    assert filtered[0].metadata["sku_offer_group"]["sku_ids"] == [
        "first",
        "second",
    ]


def test_delivery_is_reconciled_by_sku_id():
    groups = _final_groups()
    delivery = _sku("pro-white", "53.89", "GM2 Pro White", "24")
    delivery.min_delivery_days = 9
    delivery.max_delivery_days = 15
    result = SkuApiResult(
        status=SkuApiStatus.SUCCESS, product_id="p1", skus=[delivery]
    )
    metrics = SkuMetrics()
    enrich_finalists_with_delivery(
        groups, _client_result(result), True, False, metrics
    )
    all_variations = [
        variation
        for group in groups
        for variation in group.metadata["sku_offer_group"]["variations"]
    ]
    white = next(
        variation for variation in all_variations if variation["sku_id"] == "pro-white"
    )
    assert white["shipping_fee"] == "24"
    assert white["min_delivery_days"] == 9
    assert metrics.missing_skus_in_delivery_response == 3


def test_delivery_failure_does_not_remove_finalist():
    groups = _final_groups()
    result = SkuApiResult(status=SkuApiStatus.ERROR, product_id="p1")
    metrics = SkuMetrics()
    enrich_finalists_with_delivery(
        groups, _client_result(result), True, False, metrics
    )
    assert len(groups) == 2
    assert metrics.delivery_failures == 1


def test_delivery_is_not_displayed_by_default():
    groups = _final_groups()
    group = groups[0].metadata["sku_offer_group"]
    group["variations"][0]["shipping_fee"] = "0"
    group["variations"][0]["min_delivery_days"] = 12
    group["variations"][0]["max_delivery_days"] = 21
    message = format_promotion(groups[0]).text
    assert "Frete grátis estimado" not in message
    assert "Entrega estimada" not in message


def test_zero_shipping_and_delivery_are_estimated_when_enabled():
    groups = _final_groups()
    group = groups[0].metadata["sku_offer_group"]
    for variation in group["variations"]:
        variation["shipping_fee"] = "0"
        variation["min_delivery_days"] = 12
        variation["max_delivery_days"] = 21
    groups[0].metadata["display_sku_delivery"] = True
    message = format_promotion(groups[0]).text
    assert "🚚 Frete grátis estimado para o Brasil" in message
    assert "📦 Entrega estimada: 12 a 21 dias" in message


def test_paid_shipping_is_estimated_when_enabled():
    groups = _final_groups()
    group = groups[0].metadata["sku_offer_group"]
    for variation in group["variations"]:
        variation["shipping_fee"] = "24.0"
        variation["min_delivery_days"] = 9
        variation["max_delivery_days"] = 15
    groups[0].metadata["display_sku_delivery"] = True
    message = format_promotion(groups[0]).text
    assert "🚚 Frete estimado para o Brasil: R$ 24,00" in message
    assert "📦 Entrega estimada: 9 a 15 dias" in message


def test_different_delivery_conditions_are_not_generalized_to_group():
    groups = _final_groups()
    group = groups[0].metadata["sku_offer_group"]
    group["variations"][0]["shipping_fee"] = "0"
    group["variations"][1]["shipping_fee"] = "24.0"
    groups[0].metadata["display_sku_delivery"] = True
    message = format_promotion(groups[0]).text
    assert "Frete e prazo variam conforme a opção escolhida" in message
    assert "Frete grátis estimado" not in message
