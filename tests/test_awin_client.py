import httpx
import pytest

from app.clients.awin import AwinAuthError, AwinClient, AwinHttpError


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("POST", "https://api.awin.com/publisher/1/promotions"),
    )


def test_fetch_promotions_paginates_until_total(monkeypatch):
    client = AwinClient(oauth2_token="token", publisher_id="123")
    calls: list[dict] = []

    pages = {
        1: {
            "data": [{"promotionId": i} for i in range(1, 201)],
            "pagination": {"page": 1, "pageSize": 200, "total": 250},
        },
        2: {
            "data": [{"promotionId": i} for i in range(201, 251)],
            "pagination": {"page": 2, "pageSize": 200, "total": 250},
        },
    }

    def fake_post(url, headers=None, json=None):
        page = json["pagination"]["page"]
        calls.append(json)
        assert headers["Authorization"] == "Bearer token"
        assert "123" in url
        return _response(200, pages[page])

    monkeypatch.setattr(httpx.Client, "post", lambda self, *a, **k: fake_post(*a, **k))

    items = client.fetch_promotions(
        advertiser_ids=[17729, 17652, 17648],
        page_size=200,
    )

    assert len(items) == 250
    assert client.pages_fetched == 2
    assert len(calls) == 2
    assert calls[0]["filters"]["advertiserIds"] == [17729, 17652, 17648]
    assert calls[0]["filters"]["membership"] == "joined"
    assert calls[0]["filters"]["regionCodes"] == ["BR"]
    assert calls[0]["filters"]["status"] == "active"
    assert calls[0]["filters"]["type"] == "all"
    assert calls[0]["pagination"]["page"] == 1
    assert calls[1]["pagination"]["page"] == 2


def test_auth_error_raises(monkeypatch):
    client = AwinClient(oauth2_token="bad", publisher_id="123")

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, *a, **k: _response(401, {"error": "unauthorized"}),
    )

    with pytest.raises(AwinAuthError):
        client.fetch_promotions(advertiser_ids=[17729])


def test_http_error_raises(monkeypatch):
    client = AwinClient(oauth2_token="token", publisher_id="123")

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, *a, **k: _response(400, {"error": "bad"}),
    )

    with pytest.raises(AwinHttpError):
        client.fetch_promotions(advertiser_ids=[17729])
