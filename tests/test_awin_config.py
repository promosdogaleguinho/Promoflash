import json
from pathlib import Path

from app.awin_config import load_awin_advertisers
from app.awin_product_feed import ProductFeedIndex
from app.clients.awin import AwinClient
from app.collectors.awin import AwinCollector

ROOT = Path(__file__).resolve().parents[1]
LIVE_SOURCES = json.loads(
    (ROOT / "config" / "sources.json").read_text(encoding="utf-8")
)


def test_live_awin_advertisers_include_kabum_nike_cea():
    advertisers = load_awin_advertisers(LIVE_SOURCES["awin"])
    by_id = {item.id: item for item in advertisers}

    assert 17729 in by_id
    assert by_id[17729].enabled is True
    assert by_id[17729].display_name == "KaBuM"

    assert 17652 in by_id
    assert by_id[17652].enabled is True
    assert by_id[17652].display_name == "Nike"

    assert 17648 in by_id
    assert by_id[17648].enabled is True
    assert by_id[17648].display_name == "C&A"


def test_awin_collector_passes_all_enabled_advertiser_ids(monkeypatch):
    advertisers = load_awin_advertisers(LIVE_SOURCES["awin"])
    enabled_ids = [item.id for item in advertisers if item.enabled]
    assert enabled_ids == [17729, 17652, 17648]

    captured: dict = {}

    class FakeClient(AwinClient):
        def __init__(self) -> None:
            super().__init__(oauth2_token="token", publisher_id="123")

        def fetch_promotions(self, **kwargs):
            captured.update(kwargs)
            return []

    collector = AwinCollector(
        client=FakeClient(),
        advertisers=advertisers,
    )
    monkeypatch.setattr(
        collector,
        "_load_product_feed_indexes",
        lambda advertiser_ids: (ProductFeedIndex(), ProductFeedIndex()),
    )
    collector.collect()

    assert captured["advertiser_ids"] == [17729, 17652, 17648]
    assert captured["membership"] == "joined"
    assert captured["region_codes"] == ["BR"]
    assert captured["status"] == "active"
    assert captured["offer_type"] == "all"
