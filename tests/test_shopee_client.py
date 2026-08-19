import hashlib
import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.clients.shopee_affiliate import (
    ShopeeAffiliateClient,
    ShopeeAuthError,
    ShopeeGraphQLError,
    ShopeeHttpError,
    ShopeeTimeoutError,
    build_product_offer_v2_query,
)
from app.clients.shopee_signature import (
    build_authorization_header,
    build_payload,
    build_signature,
    build_timestamp,
)


def _client() -> ShopeeAffiliateClient:
    return ShopeeAffiliateClient(
        app_id="app-123",
        app_secret="secret-xyz",
        api_url="https://open-api.affiliate.shopee.com.br/graphql",
        timeout=5.0,
        page_limit=20,
        max_retries=3,
    )


class TestSignature:
    def test_timestamp_ceil(self):
        assert build_timestamp(10.1) == 11
        assert build_timestamp(10.0) == 10

    def test_payload_compact_json(self):
        payload = build_payload('query { productOfferV2 { nodes { itemId } } }')
        assert payload == (
            '{"query":"query { productOfferV2 { nodes { itemId } } }"}'
        )
        assert " " not in payload.split(":", 1)[0]

    def test_payload_preserves_accents(self):
        query = '{ productOfferV2(keyword: "tênis") { nodes { productName } } }'
        payload = build_payload(query)
        assert "tênis" in payload
        parsed = json.loads(payload)
        assert parsed["query"] == query

    def test_signature_concatenation_and_sha256(self):
        app_id = "app-123"
        timestamp = 1700000000
        payload = '{"query":"{productOfferV2{nodes{itemId}}}"}'
        secret = "secret-xyz"
        expected = hashlib.sha256(
            f"{app_id}{timestamp}{payload}{secret}".encode("utf-8")
        ).hexdigest()
        assert build_signature(app_id, timestamp, payload, secret) == expected

    def test_authorization_header(self):
        header = build_authorization_header("app-123", 1700000000, "abc123")
        assert header == (
            "SHA256 Credential=app-123, Timestamp=1700000000, Signature=abc123"
        )


class TestClientRequest:
    def test_signed_body_matches_sent_body(self):
        client = _client()
        query = build_product_offer_v2_query("notebook", page=1, limit=20)
        payload, headers = client._build_signed_request(query, now=1700000000.2)

        assert payload == build_payload(query)
        assert headers["Content-Type"] == "application/json"
        assert "Authorization" in headers
        assert "Credential=app-123" in headers["Authorization"]
        assert "Timestamp=1700000001" in headers["Authorization"]
        signature = headers["Authorization"].split("Signature=")[1]
        assert signature == build_signature(
            "app-123", 1700000001, payload, "secret-xyz"
        )

    def test_valid_response(self):
        client = _client()
        body = {
            "data": {
                "productOfferV2": {
                    "nodes": [{"itemId": 1, "shopId": 2, "productName": "A"}],
                    "pageInfo": {
                        "page": 1,
                        "limit": 20,
                        "hasNextPage": False,
                        "scrollId": None,
                    },
                }
            }
        }
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = body

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            result = client.product_offer_v2(keyword="fone", page=1, limit=20)

        assert len(result["nodes"]) == 1
        assert result["pageInfo"]["hasNextPage"] is False
        kwargs = instance.post.call_args.kwargs
        assert "json" not in kwargs
        assert "content" in kwargs

    def test_http_200_with_graphql_errors(self):
        client = _client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"errors": [{"message": "field error"}]}

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            with pytest.raises(ShopeeGraphQLError):
                client.execute("{ productOfferV2 { nodes { itemId } } }")

        assert client.metrics["graphql_errors"] == 1

    def test_http_error(self):
        client = _client()
        response = MagicMock()
        response.status_code = 400

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            with pytest.raises(ShopeeHttpError):
                client.execute("{ productOfferV2 { nodes { itemId } } }")

        assert client.metrics["http_errors"] == 1

    def test_timeout_retries_then_fails(self):
        client = ShopeeAffiliateClient(
            app_id="app-123",
            app_secret="secret-xyz",
            max_retries=2,
        )

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.side_effect = httpx.TimeoutException("timeout")
            with patch("app.clients.shopee_affiliate.time.sleep"):
                with pytest.raises(ShopeeTimeoutError):
                    client.execute("{ productOfferV2 { nodes { itemId } } }")

        assert client.metrics["timeouts"] == 2
        assert client.metrics["retries"] == 1

    def test_auth_failure(self):
        client = _client()
        response = MagicMock()
        response.status_code = 401

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            with pytest.raises(ShopeeAuthError):
                client.execute("{ productOfferV2 { nodes { itemId } } }")

        assert client.metrics["auth_failures"] == 1

    def test_product_offer_null_returns_empty(self):
        client = _client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"productOfferV2": None}}

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            result = client.product_offer_v2(page=1, limit=20)

        assert result["nodes"] == []
        assert result["pageInfo"]["hasNextPage"] is False

    def test_secret_not_logged_on_error(self, caplog):
        client = _client()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "errors": [{"message": "unauthorized signature"}]
        }

        with patch("app.clients.shopee_affiliate.httpx.Client") as client_cls:
            instance = client_cls.return_value.__enter__.return_value
            instance.post.return_value = response
            with pytest.raises(ShopeeAuthError):
                client.execute("{ productOfferV2 { nodes { itemId } } }")

        assert "secret-xyz" not in caplog.text
