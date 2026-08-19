from unittest.mock import MagicMock, patch

from app.clients.aliexpress import (
    METHOD_PRODUCT_SKU_DETAIL_GET,
    AliExpressClient,
)
from app.sku_models import SkuApiStatus


def _client() -> AliExpressClient:
    return AliExpressClient(
        app_key="key",
        app_secret="secret",
        endpoint="https://example.test/api",
        ship_to_country="BR",
        target_currency="BRL",
        target_language="PT",
    )


def _success() -> dict:
    return {
        "result": {
            "result": {
                "ae_item_sku_info": {
                    "traffic_sku_info_list": {
                        "sku_id": "1",
                        "price_with_tax": "10",
                    }
                }
            },
            "success": True,
        }
    }


def test_uses_official_method_and_required_parameters():
    client = _client()
    client.call_api = MagicMock(return_value=_success())
    client.product_sku_detail_get("p1")
    method, params = client.call_api.call_args.args
    assert method == METHOD_PRODUCT_SKU_DETAIL_GET
    assert params == {
        "ship_to_country": "BR",
        "product_id": "p1",
        "target_currency": "BRL",
        "target_language": "PT",
        "need_deliver_info": "No",
        "sku_ids": None,
    }
    assert "page_no" not in params
    assert "cursor" not in params
    assert "offset" not in params


def test_sends_comma_separated_sku_ids_for_delivery():
    client = _client()
    client.call_api = MagicMock(return_value=_success())
    client.product_sku_detail_get(
        "p1", need_deliver_info=True, sku_ids=["1", "2"]
    )
    params = client.call_api.call_args.args[1]
    assert params["need_deliver_info"] == "Yes"
    assert params["sku_ids"] == "1,2"


def test_cache_uses_product_locale_and_delivery_flag():
    client = _client()
    client.call_api = MagicMock(return_value=_success())
    first = client.product_sku_detail_get("p1", need_deliver_info=False)
    second = client.product_sku_detail_get("p1", need_deliver_info=False)
    delivery = client.product_sku_detail_get("p1", need_deliver_info=True)
    assert first is second
    assert delivery is not first
    assert client.call_api.call_count == 2


def test_cache_distinguishes_requested_sku_ids():
    client = _client()
    client.call_api = MagicMock(return_value=_success())
    client.product_sku_detail_get("p1", need_deliver_info=True, sku_ids=["1"])
    client.product_sku_detail_get("p1", need_deliver_info=True, sku_ids=["2"])
    assert client.call_api.call_count == 2


def test_transport_error_is_not_cached():
    client = _client()
    client.call_api = MagicMock(return_value={})
    first = client.product_sku_detail_get("p1")
    second = client.product_sku_detail_get("p1")
    assert first.status == SkuApiStatus.ERROR
    assert second.status == SkuApiStatus.ERROR
    assert client.call_api.call_count == 2


def test_405_is_logged_as_info(caplog):
    client = _client()
    client.call_api = MagicMock(
        return_value={
            "error_response": {"code": "15", "type": "ISP", "sub_code": "405"}
        }
    )
    with caplog.at_level("INFO"):
        result = client.product_sku_detail_get("p1")
    assert result.status == SkuApiStatus.NOT_FOUND
    assert "sub_code=405" in caplog.text


def test_other_error_is_non_blocking_warning(caplog):
    client = _client()
    client.call_api = MagicMock(
        return_value={"error_response": {"code": "15", "sub_code": "500"}}
    )
    with caplog.at_level("WARNING"):
        result = client.product_sku_detail_get("p1")
    assert result.status == SkuApiStatus.ERROR
    assert "code=500" in caplog.text


def test_reuses_existing_rate_limit_retry():
    client = _client()
    limited = {
        "error_response": {
            "code": "ApiCallLimit",
            "msg": "Api access frequency exceeds the limit",
        }
    }
    client.call_api = MagicMock(side_effect=[limited, _success()])
    with patch("app.clients.aliexpress.time.sleep") as sleep:
        result = client.product_sku_detail_get("p1")
    assert result.status == SkuApiStatus.SUCCESS
    assert client.call_api.call_count == 2
    sleep.assert_called_once()
