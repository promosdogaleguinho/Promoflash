from decimal import Decimal
from unittest.mock import MagicMock

from app.awin_landing_enrichment import (
    enrich_offer_from_landing,
    parse_landing_html,
    resolve_product_landing_url,
)
from app.collectors.awin import AwinCollector
from app.collectors.awin_mapper import AwinAdvertiserConfig


SAMPLE_HTML = """
<html><head>
<meta property="og:image" content="https://img/og.jpg" />
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Sensor KaBuM",
  "image": "https://images.kabum.com.br/produtos/fotos/617572/sensor_g.jpg",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "BRL",
    "price": 89.99,
    "availability": "https://schema.org/InStock"
  }
}
</script>
</head></html>
"""


def test_parse_landing_html_prefers_json_ld():
    product = parse_landing_html(SAMPLE_HTML)
    assert product.image_url.endswith("sensor_g.jpg")
    assert product.price == Decimal("89.99")
    assert product.currency == "BRL"
    assert product.in_stock is True


def test_resolve_product_landing_url_from_awin_tracking():
    offer = {
        "tracking_url": (
            "https://www.awin1.com/cread.php?awinmid=17729&awinaffid=1"
            "&ued=https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F617572"
        )
    }
    assert (
        resolve_product_landing_url(offer)
        == "https://www.kabum.com.br/produto/617572"
    )


def test_enrich_offer_from_landing(monkeypatch):
    def fake_fetch(url, timeout=20.0):
        assert "617572" in url
        return parse_landing_html(SAMPLE_HTML)

    monkeypatch.setattr(
        "app.awin_landing_enrichment.fetch_landing_product_data",
        fake_fetch,
    )
    offer = {
        "source": "awin",
        "kind": "promotion",
        "advertiser_id": "17729",
        "title": "Sensor",
        "tracking_url": (
            "https://www.awin1.com/cread.php?ued="
            "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F617572"
        ),
    }
    enriched = enrich_offer_from_landing(offer)
    assert enriched["price"] == 89.99
    assert "617572" in enriched["image_url"]
    assert enriched["metadata"]["landing_enriched"] is True


def test_collector_uses_landing_when_feed_missing(monkeypatch):
    from datetime import datetime, timezone

    from app.clients.awin import AwinHttpError

    client = MagicMock()
    client.pages_fetched = 1
    client.fetch_promotions.return_value = [
        {
            "promotionId": 4024439,
            "type": "promotion",
            "advertiser": {"id": 17729, "name": "Kabum BR", "joined": True},
            "title": "Sensor de Abertura",
            "description": "Sensor de Abertura",
            "startDate": "2026-07-01T00:00:00+00:00",
            "endDate": "2026-08-01T00:00:00+00:00",
            "status": "active",
            "urlTracking": (
                "https://www.awin1.com/cread.php?ued="
                "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F617572"
            ),
            "regions": {"all": True, "list": []},
        }
    ]
    client.fetch_enhanced_retail_feed.side_effect = AwinHttpError("not found")

    monkeypatch.setattr(
        "app.awin_landing_enrichment.fetch_landing_product_data",
        lambda url, timeout=20.0: parse_landing_html(SAMPLE_HTML),
    )

    collector = AwinCollector(
        client=client,
        advertisers=[AwinAdvertiserConfig(17729, "Kabum BR", "KaBuM", True)],
        now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )
    items = collector.collect()
    assert len(items) == 1
    assert items[0]["price"] == 89.99
    assert items[0]["image_url"]
    assert collector.metrics.landing_enriched == 1
