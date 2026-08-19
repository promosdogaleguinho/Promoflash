from decimal import Decimal

import pytest

from app.formatter import format_promotion
from app.models import Coupon, Promotion
from app.product_identity import build_offer_key, build_product_key
from app.sku_evaluation import derive_variation_identity, evaluate_skus
from app.sku_grouping import group_sku_promotions
from app.sku_models import SkuProperty, SkuStatus, SkuVariant


def _variant(
    sku_id: str,
    label: str,
    price: str,
    material: str = "__base__",
    cosmetic: str = "",
    currency: str = "BRL",
    grouping_dimension: str | None = None,
) -> dict:
    return {
        "sku_id": sku_id,
        "variation_label": label,
        "material_signature": material,
        "cosmetic_label": cosmetic,
        "grouping_dimension": grouping_dimension,
        "effective_price": price,
        "original_price": str(Decimal(price) * 2),
        "discount_rate": "50",
        "currency": currency,
        "image_url": f"https://example.test/{sku_id}.jpg",
        "affiliate_url": f"https://example.test/item?sku={sku_id}",
        "availability_status": "unknown",
        "sku_status": "resolved",
    }


def _promotion(sku: dict, product_id: str = "p1") -> Promotion:
    return Promotion(
        external_id=product_id,
        source="aliexpress",
        title="Produto principal",
        url="https://example.test/item",
        affiliate_url=sku["affiliate_url"],
        price=float(sku["effective_price"]),
        final_price=float(sku["effective_price"]),
        old_price=float(sku["original_price"]),
        discount_percentage=float(sku["discount_rate"]),
        image_url=sku["image_url"],
        metadata={"parent_product_id": product_id, "sku_variant": sku},
        is_official_campaign=True,
    )


def _sku_model(value: str, price: str = "10") -> SkuVariant:
    return SkuVariant(
        sku_id="s1",
        properties=[SkuProperty(name="variação", value=value)],
        variation_label=value,
        effective_price=Decimal(price),
    )


@pytest.mark.parametrize(
    ("value", "expected_material", "expected_cosmetic"),
    [
        ("GM2 Pro Black", "GM2 Pro", "Preto"),
        ("GM2 PLUS White", "GM2 PLUS", "Branco"),
        ("128 GB Black", "128 GB", "Preto"),
        ("256 GB White", "256 GB", "Branco"),
        ("110V Black", "110V", "Preto"),
        ("220V White", "220V", "Branco"),
        ("Kit 2 Black", "Kit 2", "Preto"),
        ("XL Blue", "XL", "Azul"),
    ],
)
def test_material_signature_preserves_non_cosmetic_tokens(
    value, expected_material, expected_cosmetic
):
    material, cosmetic = derive_variation_identity(_sku_model(value))
    assert material == expected_material
    assert cosmetic == expected_cosmetic


def test_combination_of_attributes_builds_material_signature():
    sku = SkuVariant(
        sku_id="s1",
        properties=[
            SkuProperty(name="cor", value="Preto"),
            SkuProperty(name="pacote", value="12G 256G"),
            SkuProperty(name="voltagem", value="110V"),
        ],
        effective_price=Decimal("100"),
    )
    material, cosmetic = derive_variation_identity(sku)
    assert material == "12G 256G • 110V"
    assert cosmetic == "Preto"


def test_unknown_color_values_are_cosmetic_variations():
    sku = SkuVariant(
        sku_id="s1",
        properties=[SkuProperty(name="cor", value="F80G")],
        effective_price=Decimal("61.59"),
    )
    material, cosmetic = derive_variation_identity(sku)
    assert material == "__base__"
    assert cosmetic == "F80G"


def test_length_is_variation_and_connector_remains_material():
    sku = _sku_model("Banana - Banana • 1,5m")
    evaluate_skus([sku], "Cabo de áudio")
    assert sku.material_signature == "Banana - Banana"
    assert sku.cosmetic_label == "1,5 m"
    assert sku.grouping_dimension == "length"


def test_sku_without_explicit_discount_can_be_resolved():
    sku = _sku_model("Preto")
    evaluate_skus([sku], "Produto principal")
    assert sku.sku_status == SkuStatus.RESOLVED
    assert sku.effective_price == Decimal("10")


def test_suspicious_accessory_sku_is_rejected():
    sku = _sku_model("Case only")
    evaluate_skus([sku], "Smartphone principal")
    assert sku.sku_status == SkuStatus.REJECTED
    assert sku.rejection_reason == "variacao_aparenta_ser_acessorio"


def test_multiple_skus_without_properties_are_unresolved():
    skus = [
        SkuVariant(sku_id="1", effective_price=Decimal("10")),
        SkuVariant(sku_id="2", effective_price=Decimal("20")),
    ]
    evaluate_skus(skus, "Produto principal")
    assert all(sku.sku_status == SkuStatus.UNRESOLVED for sku in skus)


def test_generic_placeholder_is_not_treated_as_variation():
    skus = [
        _sku_model("Color", "10"),
        SkuVariant(
            sku_id="s2",
            properties=[SkuProperty(name="cor", value="Cor")],
            variation_label="Cor",
            effective_price=Decimal("11"),
        ),
    ]
    evaluate_skus(skus, "Produto principal")
    assert all(sku.sku_status == SkuStatus.UNRESOLVED for sku in skus)
    assert all(sku.material_signature == "__base__" for sku in skus)


def test_missing_stock_does_not_reject_sku():
    sku = _sku_model("Preto")
    evaluate_skus([sku], "Produto principal")
    assert sku.availability_status == "unknown"
    assert sku.sku_status == SkuStatus.RESOLVED


def test_two_colors_with_identical_price_form_one_group():
    promotions = [
        _promotion(_variant("b", "Black", "6500", cosmetic="Preto")),
        _promotion(_variant("w", "White", "6500", cosmetic="Branco")),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 1
    assert grouped[0].metadata["sku_offer_group"]["sku_ids"] == ["b", "w"]


def test_two_colors_below_tolerance_form_one_group():
    promotions = [
        _promotion(_variant("b", "Black", "53.69", cosmetic="Preto")),
        _promotion(_variant("w", "White", "53.89", cosmetic="Branco")),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 1
    group = grouped[0].metadata["sku_offer_group"]
    assert group["minimum_price"] == "53.69"
    assert group["maximum_price"] == "53.89"


def test_two_colors_above_tolerance_form_separate_groups():
    promotions = [
        _promotion(_variant("b", "Black", "6500", cosmetic="Preto")),
        _promotion(_variant("w", "White", "6700", cosmetic="Branco")),
    ]
    assert len(group_sku_promotions(promotions)) == 2


def test_lengths_from_same_connector_family_ignore_price_tolerance():
    promotions = [
        _promotion(
            _variant(
                "1",
                "1,5 m",
                "45.99",
                "Banana - Banana",
                "1,5 m",
                grouping_dimension="length",
            )
        ),
        _promotion(
            _variant(
                "2",
                "3 m",
                "110.99",
                "Banana - Banana",
                "3 m",
                grouping_dimension="length",
            )
        ),
        _promotion(
            _variant(
                "3",
                "5 m",
                "176.59",
                "Banana - Banana",
                "5 m",
                grouping_dimension="length",
            )
        ),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 1
    message = format_promotion(grouped[0]).text
    assert "💰 A partir de R$ 45,99" in message
    assert "• 1,5 m — R$ 45,99" in message
    assert "• 3 m — R$ 110,99" in message
    assert "• 5 m — R$ 176,59" in message


def test_different_connector_families_remain_separate():
    promotions = [
        _promotion(
            _variant(
                "1",
                "1,5 m",
                "45.99",
                "Banana - Banana",
                "1,5 m",
                grouping_dimension="length",
            )
        ),
        _promotion(
            _variant(
                "2",
                "1,5 m",
                "46.89",
                "Conector Y - Plugue de Pino",
                "1,5 m",
                grouping_dimension="length",
            )
        ),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 2
    assert {
        build_product_key(promotion) for promotion in grouped
    } == {"aliexpress:product:p1"}


def test_materially_different_models_form_separate_groups():
    promotions = [
        _promotion(
            _variant("1", "GM2 Pro Black", "53.69", "GM2 Pro", "Preto")
        ),
        _promotion(
            _variant("2", "GM2 PLUS Black", "57.39", "GM2 PLUS", "Preto")
        ),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 2
    assert {item.metadata["sku_offer_group"]["material_signature"] for item in grouped} == {
        "GM2 Pro",
        "GM2 PLUS",
    }


@pytest.mark.parametrize(
    ("first_material", "second_material"),
    [
        ("128 GB", "256 GB"),
        ("Tamanho M", "Tamanho XL"),
        ("110V", "220V"),
        ("Kit 1", "Kit 2"),
    ],
)
def test_materially_different_configurations_form_separate_groups(
    first_material, second_material
):
    promotions = [
        _promotion(
            _variant("1", first_material, "100", first_material, "Preto")
        ),
        _promotion(
            _variant("2", second_material, "100", second_material, "Branco")
        ),
    ]
    assert len(group_sku_promotions(promotions)) == 2


def test_real_gm2_case_creates_two_groups_not_four():
    promotions = [
        _promotion(_variant("1", "GM2 Pro Black", "53.69", "GM2 Pro", "Preto")),
        _promotion(_variant("2", "GM2 Pro White", "53.89", "GM2 Pro", "Branco")),
        _promotion(_variant("3", "GM2 PLUS White", "57.29", "GM2 PLUS", "Branco")),
        _promotion(_variant("4", "GM2 PLUS Black", "57.39", "GM2 PLUS", "Preto")),
    ]
    grouped = group_sku_promotions(promotions)
    assert len(grouped) == 2
    assert sorted(
        len(item.metadata["sku_offer_group"]["variations"]) for item in grouped
    ) == [2, 2]
    plus_group = next(
        item
        for item in grouped
        if item.metadata["sku_offer_group"]["material_signature"] == "GM2 PLUS"
    )
    assert "GM2 PLUS" in plus_group.title
    assert "GM2 Pro" not in plus_group.title


def test_duplicate_sku_from_multiple_collectors_is_not_duplicated_in_group():
    sku = _variant("same", "Black", "100", cosmetic="Preto")
    grouped = group_sku_promotions([_promotion(sku), _promotion(dict(sku))])
    assert len(grouped) == 1
    assert len(grouped[0].metadata["sku_offer_group"]["variations"]) == 1


def test_different_coupons_do_not_group():
    first = _promotion(_variant("b", "Black", "100", cosmetic="Preto"))
    second = _promotion(_variant("w", "White", "100", cosmetic="Branco"))
    first.coupons = [Coupon(source="aliexpress", code="A")]
    second.coupons = [Coupon(source="aliexpress", code="B")]
    assert len(group_sku_promotions([first, second])) == 2


def test_offer_identity_ignores_volatile_link_and_shipping():
    promotion = group_sku_promotions(
        [_promotion(_variant("b", "Black", "100", cosmetic="Preto"))]
    )[0]
    original_key = build_offer_key(promotion)
    variation = promotion.metadata["sku_offer_group"]["variations"][0]
    variation["affiliate_url"] = "https://example.test/changed-tracking"
    variation["shipping_fee"] = "99"
    variation["delivery_days"] = 30
    assert build_offer_key(promotion) == original_key


def test_offer_identity_changes_when_single_sku_price_changes():
    first = group_sku_promotions(
        [_promotion(_variant("b", "Black", "100", cosmetic="Preto"))]
    )[0]
    second = group_sku_promotions(
        [_promotion(_variant("b", "Black", "90", cosmetic="Preto"))]
    )[0]
    assert build_offer_key(first) != build_offer_key(second)


def test_message_omits_variation_when_only_one_public_option_exists():
    promotion = group_sku_promotions(
        [_promotion(_variant("b", "Black", "100", cosmetic="Preto"))]
    )[0]
    message = format_promotion(promotion).text
    assert "Variação:" not in message
    assert "Cor:" not in message
    assert "Tamanho:" not in message


def test_message_omits_variation_when_product_has_no_meaningful_variation():
    promotion = group_sku_promotions(
        [_promotion(_variant("single", "Padrão", "100"))]
    )[0]
    message = format_promotion(promotion).text
    assert "Variação:" not in message
    assert "Variações:" not in message


def test_message_uses_plural_variations_for_equal_prices():
    promotion = group_sku_promotions(
        [
            _promotion(_variant("b", "Black", "100", cosmetic="Preto")),
            _promotion(_variant("w", "White", "100", cosmetic="Branco")),
        ]
    )[0]
    message = format_promotion(promotion).text
    assert "🏷️ Variações: Preto, Branco" in message
    assert "A partir de" not in message


def test_message_deduplicates_repeated_public_variations():
    promotion = group_sku_promotions(
        [
            _promotion(_variant("1", "F80G", "61.59", cosmetic="F80G")),
            _promotion(_variant("2", "F80G", "61.59", cosmetic="F80G")),
            _promotion(_variant("3", "F80W", "61.59", cosmetic="F80W")),
            _promotion(_variant("4", "A5-B", "61.59", cosmetic="A5-B")),
            _promotion(_variant("5", "A5-S", "61.59", cosmetic="A5-S")),
        ]
    )[0]
    message = format_promotion(promotion).text
    assert "🏷️ Variações: F80G, F80W, A5-B, A5-S" in message
    assert message.count("F80G") == 1


def test_message_uses_starting_at_and_prices_for_near_prices():
    promotion = group_sku_promotions(
        [
            _promotion(_variant("b", "Black", "53.69", cosmetic="Preto")),
            _promotion(_variant("w", "White", "53.89", cosmetic="Branco")),
        ]
    )[0]
    message = format_promotion(promotion).text
    assert "💰 A partir de R$ 53,69" in message
    assert "• Preto — R$ 53,69" in message
    assert "• Branco — R$ 53,89" in message
