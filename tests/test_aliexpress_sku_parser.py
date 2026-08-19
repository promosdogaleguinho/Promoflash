import json
from decimal import Decimal

import pytest

from app.aliexpress_sku_parser import parse_sku_detail_response
from app.sku_models import SkuApiStatus, SkuMetrics

def _streamlined(sku_info: object, success: object = True) -> dict:
    return {
        "result": {
            "result": {
                "ae_item_info": {"product_id": "p1"},
                "ae_item_sku_info": sku_info,
            },
            "success": success,
            "code": 200,
        }
    }


def _sku(**overrides) -> dict:
    raw = {
        "sku_id": "s1",
        "sku_properties": '[{"cor":"Black","Pacote":"12G 256G"}]',
        "price_with_tax": "100.00",
        "sale_price_with_tax": "80.00",
        "discount_rate": "20",
        "currency": "BRL",
        "sku_image_link": "https://example.test/image.jpg",
        "link": "https://example.test/item",
    }
    raw.update(overrides)
    return raw


def test_parses_real_non_refinement_single_sku():
    response = {
        "aliexpress_affiliate_product_sku_detail_get_response": {
            "result": {
                "result": {
                    "ae_item_info": {"product_id": "1005007517522403"},
                    "ae_item_sku_info": {
                        "traffic_sku_info_list": [
                            _sku(
                                price_with_tax="2129.22",
                                sale_price_with_tax="1383.99",
                                sku_properties=(
                                    '[{"cor":"Black","Pacote":"12G 256G"}]'
                                ),
                                shipping_fees="0",
                                min_delivery_days="12",
                                max_delivery_days="21",
                            )
                        ]
                    },
                },
                "code": 200,
                "success": True,
            }
        }
    }
    result = parse_sku_detail_response(
        response,
        "1005007517522403",
    )
    assert result.status == SkuApiStatus.SUCCESS
    assert result.item_info["product_id"] == "1005007517522403"
    assert len(result.skus) == 1
    sku = result.skus[0]
    assert sku.variation_label == "Preto • 12G 256G"
    assert sku.original_price == Decimal("2129.22")
    assert sku.sale_price == Decimal("1383.99")
    assert sku.effective_price == Decimal("1383.99")
    assert sku.availability_status == "unknown"
    assert sku.shipping_fee == Decimal("0")
    assert sku.min_delivery_days == 12
    assert sku.max_delivery_days == 21


def test_parses_real_streamlined_multiple_skus_and_string_success():
    skus = [
        _sku(
            sku_id=str(index),
            sale_price_with_tax=price,
            sku_properties=f'[{{"cor":"{label}"}}]',
        )
        for index, (label, price) in enumerate(
            [
                ("GM2 Pro Black", "53.69"),
                ("GM2 Pro White", "53.89"),
                ("GM2 PLUS White", "57.29"),
                ("GM2 PLUS Black", "57.39"),
            ],
            start=1,
        )
    ]
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": skus}, "true"),
        "1005007572968437",
    )
    assert result.status == SkuApiStatus.SUCCESS
    assert len(result.skus) == 4
    assert result.skus[0].effective_price == Decimal("53.69")


@pytest.mark.parametrize(
    "sku_info",
    [
        {"traffic_sku_info_list": [_sku()]},
        {"traffic_sku_info_list": _sku()},
        [_sku()],
    ],
)
def test_accepts_supported_sku_containers(sku_info):
    result = parse_sku_detail_response(_streamlined(sku_info), "p1")
    assert len(result.skus) == 1


@pytest.mark.parametrize("success", [True, "true", "TRUE"])
def test_accepts_boolean_and_string_success(success):
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [_sku()]}, success), "p1"
    )
    assert result.status == SkuApiStatus.SUCCESS


def test_rejects_false_string_success():
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [_sku()]}, "false"), "p1"
    )
    assert result.status == SkuApiStatus.ERROR


def test_rejects_failed_envelope_without_payload():
    response = {"result": {"success": False, "code": "500"}}
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.ERROR
    assert result.error_code == "500"


def test_rejects_non_success_code_even_when_payload_exists():
    response = _streamlined({"traffic_sku_info_list": [_sku()]})
    response["result"]["code"] = 500
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.ERROR
    assert result.error_code == "500"


def test_accepts_json_serialized_result_envelopes():
    payload = {
        "ae_item_info": {"product_id": "p1"},
        "ae_item_sku_info": {"traffic_sku_info_list": [_sku()]},
    }
    response = {
        "result": json.dumps(
            {"result": json.dumps(payload), "success": "true", "code": 200}
        )
    }
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.SUCCESS
    assert len(result.skus) == 1


def test_parses_sku_properties_list():
    raw = _sku(sku_properties=[{"color": "White"}, {"size": "XL"}])
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1"
    )
    assert result.skus[0].variation_label == "Branco • XL"


def test_parses_sku_properties_object():
    raw = _sku(sku_properties={"color": "Blue", "size": "M"})
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1"
    )
    assert result.skus[0].variation_label == "Azul • M"


def test_invalid_properties_use_specific_field_fallback_without_raising():
    metrics = SkuMetrics()
    raw = _sku(sku_properties="{bad-json", color="Black")
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1", metrics
    )
    assert result.skus[0].variation_label == "Preto"
    assert result.skus[0].raw["sku_properties"] == "{bad-json"
    assert metrics.invalid_properties == 1


def test_ignores_empty_properties():
    raw = _sku(sku_properties=[{"cor": "", "Pacote": None}])
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1"
    )
    assert result.skus[0].properties == []


def test_sale_price_has_priority_over_regular_price():
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [_sku()]}), "p1"
    )
    assert result.skus[0].effective_price == Decimal("80.00")


def test_regular_price_is_fallback_without_sale_or_discount():
    raw = _sku(sale_price_with_tax=None, discount_rate=None)
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1"
    )
    assert result.skus[0].effective_price == Decimal("100.00")
    assert result.skus[0].discount_rate is None


def test_missing_prices_do_not_create_fictitious_value():
    raw = _sku(price_with_tax=None, sale_price_with_tax=None)
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": [raw]}), "p1"
    )
    assert result.skus[0].effective_price is None


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"result": {}},
        _streamlined({}),
        _streamlined({"traffic_sku_info_list": []}),
    ],
)
def test_empty_and_incomplete_responses(response):
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.EMPTY
    assert result.skus == []


def test_405_is_expected_not_found_result():
    response = {
        "error_response": {"code": "15", "type": "ISP", "sub_code": "405"}
    }
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.NOT_FOUND
    assert result.error_code == "405"


def test_other_api_error_is_non_success_result():
    response = {
        "error_response": {"code": "15", "type": "ISP", "sub_code": "500"}
    }
    result = parse_sku_detail_response(response, "p1")
    assert result.status == SkuApiStatus.ERROR


def test_exactly_twenty_skus_marks_incomplete_coverage():
    raws = [_sku(sku_id=str(index)) for index in range(20)]
    result = parse_sku_detail_response(
        _streamlined({"traffic_sku_info_list": raws}), "p1"
    )
    assert len(result.skus) == 20
    assert result.coverage_may_be_incomplete is True
