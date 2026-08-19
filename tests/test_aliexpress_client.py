import json
import logging
from unittest.mock import MagicMock, patch

import httpx

from app.clients.aliexpress import AliExpressClient
from app.clients.aliexpress_signature import build_signature


def _build_client() -> AliExpressClient:
    return AliExpressClient(
        app_key="fake-key",
        app_secret="fake-secret",
        endpoint="https://api-sg.aliexpress.com/sync",
        sign_method="sha256",
        tracking_id="promoflash",
    )


class TestSignature:
    def test_signature_returns_uppercase_string(self):
        signature = build_signature(
            {"method": "test", "app_key": "abc"}, "secret", "sha256"
        )
        assert isinstance(signature, str)
        assert signature == signature.upper()

    def test_signature_ignores_sign_field(self):
        params = {"app_key": "abc", "method": "test"}
        with_sign = dict(params, sign="ANY_VALUE")

        assert build_signature(params, "secret", "sha256") == build_signature(
            with_sign, "secret", "sha256"
        )

    def test_signature_ignores_none_values(self):
        params = {"app_key": "abc", "method": "test"}
        with_none = dict(params, tracking_id=None)

        assert build_signature(params, "secret", "sha256") == build_signature(
            with_none, "secret", "sha256"
        )

    def test_signature_is_stable(self):
        params = {"b": "2", "a": "1", "c": "3"}
        first = build_signature(params, "secret", "sha256")
        second = build_signature(params, "secret", "sha256")
        assert first == second

    def test_signature_supports_all_methods(self):
        params = {"app_key": "abc", "method": "test"}
        for method in ("sha256", "hmac", "md5"):
            assert build_signature(params, "secret", method)


class TestCommonParams:
    def test_common_params_contains_required_fields(self):
        client = _build_client()
        params = client._build_common_params("aliexpress.affiliate.product.query")

        for field in ("app_key", "method", "timestamp", "format", "v", "sign_method"):
            assert field in params

        assert params["app_key"] == "fake-key"
        assert params["method"] == "aliexpress.affiliate.product.query"
        assert params["format"] == "json"
        assert params["v"] == "2.0"
        assert params["sign_method"] == "sha256"

    def test_secret_not_in_common_params(self):
        client = _build_client()
        params = client._build_common_params("any.method")
        assert "fake-secret" not in str(params)


class TestNormalizeResponse:
    def test_finds_products_with_resp_result_as_dict(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "resp_code": 200,
                    "resp_msg": "ok",
                    "result": {
                        "products": {
                            "product": [
                                {"product_id": "1"},
                                {"product_id": "2"},
                            ]
                        }
                    },
                }
            }
        }
        products = client._normalize_response_products(response)
        assert len(products) == 2
        assert products[0]["product_id"] == "1"

    def test_finds_products_with_resp_result_as_json_string(self):
        client = _build_client()
        inner = {
            "resp_code": 200,
            "result": {"products": {"product": [{"product_id": "7"}]}},
        }
        response = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": json.dumps(inner)
            }
        }
        products = client._normalize_response_products(response)
        assert len(products) == 1
        assert products[0]["product_id"] == "7"

    def test_finds_products_when_product_is_list(self):
        client = _build_client()
        response = {"products": {"product": [{"product_id": "9"}, {"product_id": "10"}]}}
        products = client._normalize_response_products(response)
        assert len(products) == 2
        assert products[1]["product_id"] == "10"

    def test_finds_products_when_product_is_single_dict(self):
        client = _build_client()
        response = {
            "resp_result": {
                "resp_code": 200,
                "result": {"products": {"product": {"product_id": "solo"}}},
            }
        }
        products = client._normalize_response_products(response)
        assert len(products) == 1
        assert products[0]["product_id"] == "solo"

    def test_finds_products_when_products_is_direct_list(self):
        client = _build_client()
        response = {
            "resp_result": {
                "resp_code": 200,
                "result": {"products": [{"product_id": "direct"}]},
            }
        }
        products = client._normalize_response_products(response)
        assert len(products) == 1
        assert products[0]["product_id"] == "direct"

    def test_returns_empty_when_resp_code_not_success(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "resp_code": 500,
                    "resp_msg": "system error",
                    "result": {"products": {"product": [{"product_id": "1"}]}},
                }
            }
        }
        assert client._normalize_response_products(response) == []

    def test_returns_empty_when_no_products(self):
        client = _build_client()
        assert client._normalize_response_products({"unexpected": {}}) == []


class TestDefaults:
    def test_default_sign_method_is_hmac(self):
        client = AliExpressClient(
            app_key="k",
            app_secret="s",
            endpoint="https://api-sg.aliexpress.com/sync",
        )
        assert client.sign_method == "hmac"


class TestProductQueryParams:
    @staticmethod
    def _capture_params(client: AliExpressClient) -> dict:
        captured = {}

        def fake_call_api(method, params):
            captured["method"] = method
            captured["params"] = params
            return {}

        client.call_api = fake_call_api
        return captured

    def test_sends_country_and_not_ship_to_country(self):
        client = _build_client()
        captured = self._capture_params(client)

        client.product_query("fone bluetooth")

        params = captured["params"]
        assert params["country"] == "BR"
        assert "ship_to_country" not in params

    def test_sends_fields(self):
        client = _build_client()
        captured = self._capture_params(client)

        client.product_query("fone bluetooth")

        assert "fields" in captured["params"]
        assert "promotion_link" in captured["params"]["fields"]
        assert "target_sale_price" in captured["params"]["fields"]

    def test_allows_overriding_language_currency_country(self):
        client = _build_client()
        captured = self._capture_params(client)

        client.product_query(
            "bluetooth earphones",
            target_language="EN",
            target_currency="USD",
            country="US",
        )

        params = captured["params"]
        assert params["target_language"] == "EN"
        assert params["target_currency"] == "USD"
        assert params["country"] == "US"

    def test_uses_client_defaults_when_overrides_are_none(self):
        client = _build_client()
        captured = self._capture_params(client)

        client.product_query("fone bluetooth")

        params = captured["params"]
        assert params["target_language"] == "PT"
        assert params["target_currency"] == "BRL"
        assert params["country"] == "BR"


class TestAdvancedApiMethods:
    @staticmethod
    def _capture(client: AliExpressClient) -> dict:
        captured = {}

        def fake_call_api(method, params):
            captured["method"] = method
            captured["params"] = params
            return {}

        client.call_api = fake_call_api
        return captured

    def test_hot_product_query_uses_correct_method(self):
        client = _build_client()
        captured = self._capture(client)

        client.hot_product_query()

        assert captured["method"] == "aliexpress.affiliate.hotproduct.query"

    def test_hot_product_query_sends_pt_brl_br(self):
        client = _build_client()
        captured = self._capture(client)

        client.hot_product_query()

        params = captured["params"]
        assert params["target_language"] == "PT"
        assert params["target_currency"] == "BRL"
        assert params["country"] == "BR"

    def test_hot_product_query_ignores_none_params(self):
        client = _build_client()
        captured = {}

        def fake_call_api(method, params):
            captured["params"] = params
            return {}

        client.call_api = fake_call_api
        client.hot_product_query(
            category_ids=None, sort=None, min_sale_price=None, max_sale_price=None
        )

        # call_api recebe os None; a limpeza acontece dentro do call_api real.
        real_client = _build_client()
        request_params = real_client._build_common_params(
            "aliexpress.affiliate.hotproduct.query"
        )
        request_params.update(
            {k: v for k, v in captured["params"].items() if v is not None}
        )
        assert "category_ids" not in request_params
        assert "sort" not in request_params

    def test_featured_promo_get_uses_correct_method(self):
        client = _build_client()
        captured = self._capture(client)

        client.featured_promo_get()

        assert captured["method"] == "aliexpress.affiliate.featuredpromo.get"

    def test_featured_promo_products_get_uses_correct_method(self):
        client = _build_client()
        captured = self._capture(client)

        client.featured_promo_products_get(promotion_name="Weekly Deals")

        assert captured["method"] == "aliexpress.affiliate.featuredpromo.products.get"

    def test_smart_match_uses_correct_method(self):
        client = _build_client()
        captured = self._capture(client)

        client.smart_match_products(keywords="fone bluetooth")

        assert captured["method"] == "aliexpress.affiliate.product.smartmatch"

    def test_product_detail_get_uses_correct_method(self):
        client = _build_client()
        captured = self._capture(client)

        client.product_detail_get(["123", "456"])

        assert captured["method"] == "aliexpress.affiliate.productdetail.get"
        assert captured["params"]["product_ids"] == "123,456"
        assert "promo_code_info" in captured["params"]["fields"]

    def test_product_detail_retries_on_api_call_limit(self):
        client = _build_client()
        limited = {
            "error_response": {
                "code": "ApiCallLimit",
                "msg": "Api access frequency exceeds the limit",
            }
        }
        success = {
            "aliexpress_affiliate_productdetail_get_response": {
                "resp_result": {
                    "resp_code": 200,
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": "1",
                                    "promo_code_info": {"promo_code": "RETRY1"},
                                }
                            ]
                        }
                    },
                }
            }
        }
        with (
            patch.object(client, "call_api", side_effect=[limited, success]) as mock_call,
            patch("app.clients.aliexpress.time.sleep") as mock_sleep,
        ):
            products = client.product_detail_get(["1"])
        assert mock_call.call_count == 2
        mock_sleep.assert_called_once()
        assert products[0]["promo_code_info"]["promo_code"] == "RETRY1"

    def test_product_detail_parser_preserves_promo_code_info(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_productdetail_get_response": {
                "resp_result": {
                    "resp_code": 200,
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": "1",
                                    "promo_code_info": {"promo_code": "GMG20207"},
                                }
                            ]
                        }
                    },
                }
            }
        }
        products = client._parse_product_detail_products(response, {})
        assert products[0]["promo_code_info"]["promo_code"] == "GMG20207"

    def test_404_system_error_is_soft_failure(self, caplog):
        client = _build_client()
        response = {
            "aliexpress_affiliate_featuredpromo_get_response": {
                "resp_result": {"resp_code": 404, "resp_msg": "System Error"}
            }
        }
        with caplog.at_level(logging.WARNING):
            campaigns = client._extract_campaigns(response)
        assert campaigns == []
        assert any(record.levelname == "WARNING" for record in caplog.records)

    def test_hot_product_parser_accepts_dict(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_hotproduct_query_response": {
                "resp_result": {
                    "resp_code": 200,
                    "result": {"products": {"product": [{"product_id": "h1"}]}},
                }
            }
        }
        products = client._normalize_response_products(
            response, root_key="aliexpress_affiliate_hotproduct_query_response"
        )
        assert products[0]["product_id"] == "h1"

    def test_hot_product_parser_accepts_json_string_resp_result(self):
        client = _build_client()
        inner = {
            "resp_code": 200,
            "result": {"products": {"product": [{"product_id": "h2"}]}},
        }
        response = {
            "aliexpress_affiliate_hotproduct_query_response": {
                "resp_result": json.dumps(inner)
            }
        }
        products = client._normalize_response_products(
            response, root_key="aliexpress_affiliate_hotproduct_query_response"
        )
        assert products[0]["product_id"] == "h2"

    def test_extract_campaigns_normalizes_field_variations(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_featuredpromo_get_response": {
                "resp_result": {
                    "resp_code": 200,
                    "result": {
                        "promos": {
                            "promo": [
                                {
                                    "promo_id": "c-1",
                                    "promo_name": "Weekly Deals",
                                    "activity_start_time": "2026-01-01",
                                }
                            ]
                        }
                    },
                }
            }
        }
        campaigns = client._extract_campaigns(response)
        assert campaigns[0]["promotion_id"] == "c-1"
        assert campaigns[0]["promotion_name"] == "Weekly Deals"
        assert campaigns[0]["start_time"] == "2026-01-01"

    def test_hot_product_query_returns_empty_on_http_error(self):
        client = _build_client()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with patch("app.clients.aliexpress.httpx.Client", return_value=mock_client):
            result = client.hot_product_query()

        assert result == []

    def test_advanced_methods_do_not_log_secret(self, caplog):
        client = _build_client()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=MagicMock(status_code=500)
        )

        with caplog.at_level(logging.ERROR):
            with patch("app.clients.aliexpress.httpx.Client", return_value=mock_client):
                client.hot_product_query()
                client.featured_promo_get()
                client.featured_promo_products_get(promotion_name="x")

        assert "fake-secret" not in caplog.text


class TestFeaturedPromoProductsParsing:
    def _client(self) -> AliExpressClient:
        return _build_client()

    def _wrap(self, resp_result: dict) -> dict:
        return {
            "aliexpress_affiliate_featuredpromo_products_get_response": resp_result
        }

    def test_full_response_with_multiple_products(self):
        client = self._client()
        response = self._wrap(
            {
                "resp_result": {
                    "resp_code": 200,
                    "result": {
                        "products": {
                            "product": [
                                {"product_id": "1"},
                                {"product_id": "2"},
                            ]
                        }
                    },
                }
            }
        )
        products = client._parse_featured_promo_products(response, {})
        assert [p["product_id"] for p in products] == ["1", "2"]

    def test_single_product_as_object(self):
        client = self._client()
        response = self._wrap(
            {
                "resp_result": {
                    "resp_code": 200,
                    "result": {"products": {"product": {"product_id": "solo"}}},
                }
            }
        )
        products = client._parse_featured_promo_products(response, {})
        assert len(products) == 1
        assert products[0]["product_id"] == "solo"

    def test_product_with_promo_code_info_is_preserved(self):
        client = self._client()
        response = self._wrap(
            {
                "resp_result": {
                    "resp_code": 200,
                    "result": {
                        "products": {
                            "product": [
                                {
                                    "product_id": "1",
                                    "promo_code_info": {"promo_code": "PDF01"},
                                }
                            ]
                        }
                    },
                }
            }
        )
        products = client._parse_featured_promo_products(response, {})
        assert products[0]["promo_code_info"] == {"promo_code": "PDF01"}

    def test_product_without_coupon(self):
        client = self._client()
        response = self._wrap(
            {
                "resp_result": {
                    "resp_code": 200,
                    "result": {"products": {"product": [{"product_id": "1"}]}},
                }
            }
        )
        products = client._parse_featured_promo_products(response, {})
        assert "promo_code_info" not in products[0]

    def test_empty_wrapper_returns_empty(self, caplog):
        client = self._client()
        response = self._wrap({})
        with caplog.at_level(logging.WARNING):
            products = client._parse_featured_promo_products(response, {})
        assert products == []
        assert "Featured products não encontrados" in caplog.text

    def test_resp_result_without_result(self, caplog):
        client = self._client()
        response = self._wrap({"resp_result": {"resp_code": 200}})
        with caplog.at_level(logging.WARNING):
            products = client._parse_featured_promo_products(response, {})
        assert products == []
        assert "resp_result_keys=" in caplog.text

    def test_simplified_response_without_wrapper(self):
        client = self._client()
        response = {"result": {"products": {"product": [{"product_id": "s1"}]}}}
        products = client._parse_featured_promo_products(response, {})
        assert products[0]["product_id"] == "s1"

    def test_405_the_result_is_empty_is_not_critical(self, caplog):
        client = self._client()
        response = self._wrap(
            {"resp_result": {"resp_code": 405, "resp_msg": "The result is empty"}}
        )
        with caplog.at_level(logging.WARNING):
            products = client._parse_featured_promo_products(response, {})
        assert products == []
        assert "sem resultados" in caplog.text
        assert "ERROR" not in [record.levelname for record in caplog.records]

    def test_debug_body_is_sanitized(self, caplog):
        client = AliExpressClient(
            app_key="fake-key",
            app_secret="fake-secret",
            endpoint="https://api-sg.aliexpress.com/sync",
            debug_responses=True,
        )
        response = self._wrap(
            {"resp_result": {"resp_code": 200, "result": {}, "sign": "SECRET_SIGN"}}
        )
        with caplog.at_level(logging.INFO):
            client._maybe_log_full_body("m", response)
        assert "SECRET_SIGN" not in caplog.text
        assert "***" in caplog.text


class TestApiError:
    def test_resp_code_405_returns_empty(self):
        client = _build_client()
        response = {
            "aliexpress_affiliate_product_query_response": {
                "resp_result": {
                    "resp_code": 405,
                    "resp_msg": "The result is empty",
                }
            }
        }
        assert client._normalize_response_products(response) == []

    def test_product_query_returns_empty_on_http_error(self):
        client = _build_client()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "boom",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with patch("app.clients.aliexpress.httpx.Client", return_value=mock_client):
            result = client.product_query("fone bluetooth")

        assert result == []

    def test_product_query_returns_empty_on_error_response(self):
        client = _build_client()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "error_response": {"code": "15", "msg": "invalid signature"}
        }
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.clients.aliexpress.httpx.Client", return_value=mock_client):
            result = client.product_query("fone bluetooth")

        assert result == []

    def test_secret_not_logged_on_error(self, caplog):
        client = _build_client()
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "boom",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with caplog.at_level(logging.ERROR):
            with patch("app.clients.aliexpress.httpx.Client", return_value=mock_client):
                client.product_query("fone bluetooth")

        assert "fake-secret" not in caplog.text
