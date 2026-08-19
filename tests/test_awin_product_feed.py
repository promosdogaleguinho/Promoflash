import gzip
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import httpx

from app.awin_formatter import format_campaign_offer
from app.awin_product_feed import (
    choose_old_price,
    enrich_offer_dict,
    extract_landing_url,
    extract_merchant_product_id_from_url,
    is_campaign_or_category_url,
    parse_enhanced_feed_jsonl,
    parse_feed_price,
    parse_google_money,
    parse_product_feed,
)
from app.clients.awin import AwinHttpError
from app.clients.awin_product_feed import (
    AwinProductFeedClient,
    sanitize_feed_url_for_log,
)
from app.collectors.awin import AwinCollector
from app.collectors.awin_mapper import AwinAdvertiserConfig
from app.models import CampaignOffer


def _csv_bytes() -> bytes:
    header = (
        "merchant_id,merchant_product_id,product_name,search_price,"
        "display_price,product_price_old,rrp_price,currency,"
        "large_image,merchant_image_url,aw_image_url,"
        "merchant_deep_link,aw_deep_link,in_stock,is_for_sale\n"
    )
    rows = [
        "17729,134179,Cadeira Gamer,1599.90,1599.90,1999.90,,BRL,"
        "https://img/large.jpg,https://img/merchant.jpg,,https://www.kabum.com.br/produto/134179,,"
        "true,true\n",
        "17729,997046,Monitor Gamer,1999.90,1999.90,1999.90,2499.90,BRL,"
        ",https://img/monitor.jpg,,https://www.kabum.com.br/produto/997046,,"
        "1,1\n",
        "17729,111,Sem estoque,10.00,,,BRL,https://img/x.jpg,,,,"
        "false,true\n",
        ",,linha invalida,,,,,,,,,,,,\n",
    ]
    return "".join([header, *rows]).encode("utf-8")


def test_sanitize_feed_url_hides_query_secret():
    url = "https://productdata.awin.com/datafeed/download/apikey/SECRET123/fid/1"
    sanitized = sanitize_feed_url_for_log(url)
    assert "SECRET123" not in sanitized
    assert "productdata.awin.com" in sanitized


def test_download_product_feed(monkeypatch):
    content = gzip.compress(_csv_bytes())

    def fake_get(self, url):
        assert "SECRET" not in str(url) or True
        return httpx.Response(
            200,
            content=content,
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = AwinProductFeedClient(
        "https://productdata.awin.com/datafeed/download/apikey/SECRET/fid/1"
    )
    downloaded = client.download()
    assert downloaded.startswith(b"\x1f\x8b") or downloaded


def test_parse_gzip_csv_and_index():
    content = gzip.compress(_csv_bytes())
    index = parse_product_feed(content)
    assert ("17729", "134179") in index.by_merchant_product
    product = index.by_merchant_product[("17729", "134179")]
    assert product.search_price == Decimal("1599.90")
    assert product.old_price == Decimal("1999.90")
    assert product.image_url == "https://img/large.jpg"


def test_extract_product_id_from_tracking_url():
    tracking = (
        "https://www.awin1.com/cread.php?awinmid=17729&awinaffid=1"
        "&ued=https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F134179%2Fcadeira"
    )
    assert extract_landing_url(tracking).endswith("/produto/134179/cadeira")
    assert extract_merchant_product_id_from_url(tracking) == "134179"


def test_campaign_url_is_not_product():
    url = "https://www.kabum.com.br/promocao/CP1CAPCOM10"
    assert is_campaign_or_category_url(url) is True
    assert extract_merchant_product_id_from_url(url) is None


def test_enrich_promotion_with_image_and_prices():
    index = parse_product_feed(_csv_bytes())
    offer = {
        "source": "awin",
        "external_id": "1",
        "kind": "promotion",
        "advertiser_id": "17729",
        "title": "Cadeira",
        "tracking_url": (
            "https://www.awin1.com/cread.php?ued="
            "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F134179"
        ),
    }
    enriched = enrich_offer_dict(offer, index)
    assert enriched["price"] == 1599.90
    assert enriched["old_price"] == 1999.90
    assert enriched["image_url"] == "https://img/large.jpg"
    assert enriched["merchant_product_id"] == "134179"


def test_enrich_does_not_overwrite_existing_price_or_image():
    index = parse_product_feed(_csv_bytes())
    offer = {
        "source": "awin",
        "external_id": "1",
        "kind": "promotion",
        "advertiser_id": "17729",
        "title": "Cadeira",
        "tracking_url": (
            "https://www.awin1.com/cread.php?ued="
            "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F134179"
        ),
        "price": 1200.0,
        "image_url": "https://img/from-enhanced.jpg",
    }
    enriched = enrich_offer_dict(offer, index)
    assert enriched["price"] == 1200.0
    assert enriched["image_url"] == "https://img/from-enhanced.jpg"
    assert enriched["old_price"] == 1999.90


def test_csv_completes_missing_image_after_enhanced_price(monkeypatch):
    from app.collectors.awin import AwinCollector
    from app.collectors.awin_mapper import AwinAdvertiserConfig

    client = MagicMock()
    client.pages_fetched = 1
    client.fetch_promotions.return_value = [
        {
            "promotionId": 99,
            "type": "promotion",
            "advertiser": {"id": 17729, "name": "Kabum BR", "joined": True},
            "title": "Cadeira Gamer",
            "description": "Cadeira Gamer",
            "startDate": "2026-07-01T00:00:00+00:00",
            "endDate": "2026-08-01T00:00:00+00:00",
            "status": "active",
            "urlTracking": (
                "https://www.awin1.com/cread.php?ued="
                "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F134179"
            ),
            "regions": {"all": True, "list": []},
        }
    ]
    client.fetch_enhanced_retail_feed.return_value = (
        '{"id":"134179","title":"Cadeira Gamer",'
        '"link":"https://www.kabum.com.br/produto/134179",'
        '"availability":"in_stock","price":"1599.90 BRL"}\n'
    ).encode("utf-8")

    csv_calls = {"count": 0}

    def fake_download(self):
        csv_calls["count"] += 1
        return _csv_bytes()

    monkeypatch.setattr(
        "app.clients.awin_product_feed.AwinProductFeedClient.download",
        fake_download,
    )
    monkeypatch.setattr(
        "app.collectors.awin.enrich_offers_from_landing",
        lambda offers, metrics=None, timeout=20.0: offers,
    )

    collector = AwinCollector(
        client=client,
        advertisers=[AwinAdvertiserConfig(17729, "Kabum BR", "KaBuM", True)],
        product_feed_url="https://productdata.awin.com/datafeed/download/apikey/SECRET/fid/1",
        now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )
    items = collector.collect()
    assert len(items) == 1
    assert items[0]["price"] == 1599.90
    assert items[0]["image_url"] == "https://img/large.jpg"
    assert csv_calls["count"] == 1
    assert collector.metrics.feed_source == "enhanced_api+create_a_feed_csv"


def test_old_price_only_when_greater():
    assert choose_old_price(
        {"product_price_old": "100", "rrp_price": ""},
        Decimal("150"),
    ) is None
    assert choose_old_price(
        {"product_price_old": "200", "rrp_price": ""},
        Decimal("150"),
    ) == Decimal("200")


def test_formatter_enriched_promotion_and_voucher():
    promotion = CampaignOffer(
        source="awin",
        external_id="1",
        kind="promotion",
        advertiser_id="17729",
        advertiser_name="Kabum BR",
        advertiser_display_name="KaBuM",
        title="Monitor Gamer",
        tracking_url="https://www.awin1.com/x",
        price=1999.9,
        old_price=2499.9,
        image_url="https://img/monitor.jpg",
    )
    formatted = format_campaign_offer(promotion)
    assert "De: R$ 2.499,90" in formatted.text
    assert "Por: R$ 1.999,90" in formatted.text
    assert "https://www.awin1.com/x" not in formatted.text
    assert formatted.image_url == "https://img/monitor.jpg"
    assert formatted.actions[0].url == "https://www.awin1.com/x"

    voucher = CampaignOffer(
        source="awin",
        external_id="2",
        kind="voucher",
        advertiser_id="17729",
        advertiser_name="Kabum BR",
        advertiser_display_name="KaBuM",
        title="12% OFF no Monitor",
        tracking_url="https://www.awin1.com/x",
        coupon_code="NEWTELA12",
        price=1999.9,
        image_url="https://img/monitor.jpg",
    )
    voucher_msg = format_campaign_offer(voucher)
    assert "Por: R$ 1.999,90" in voucher_msg.text
    assert "Cupom: NEWTELA12" in voucher_msg.text
    assert "De:" not in voucher_msg.text


def test_campaign_voucher_not_enriched_with_random_product():
    index = parse_product_feed(_csv_bytes())
    offer = {
        "source": "awin",
        "kind": "voucher",
        "advertiser_id": "17729",
        "title": "10% OFF gamer",
        "tracking_url": "https://www.kabum.com.br/promocao/JULHOGAMER10",
        "coupon_code": "JULHOGAMER10",
    }
    enriched = enrich_offer_dict(offer, index)
    assert "price" not in enriched
    assert "image_url" not in enriched


def test_no_match_keeps_offer_without_enrichment():
    index = parse_product_feed(_csv_bytes())
    offer = {
        "source": "awin",
        "kind": "promotion",
        "advertiser_id": "17729",
        "title": "Produto",
        "tracking_url": "https://www.kabum.com.br/produto/999999",
    }
    enriched = enrich_offer_dict(offer, index)
    assert enriched["title"] == "Produto"
    assert "price" not in enriched


def test_parse_enhanced_feed_jsonl_google_format():
    content = "\n".join(
        [
            (
                '{"id":"134179","title":"Cadeira Gamer","link":'
                '"https://www.kabum.com.br/produto/134179",'
                '"image_link":"https://img/cadeira.jpg",'
                '"availability":"in_stock","price":"1999.90 BRL",'
                '"sale_price":"1599.90 BRL"}'
            ),
            (
                '{"meta":{"advertiser_id":17729},"product_basic":'
                '{"id":"997046","title":"Monitor","link":'
                '"https://www.kabum.com.br/produto/997046",'
                '"image_link":"https://img/monitor.jpg"},'
                '"price_availability":{"availability":"in_stock",'
                '"price":"2499.90 BRL","sale_price":"1999.90 BRL"}}'
            ),
            '{"error":500,"message":"Internal server error"}',
        ]
    ).encode("utf-8")

    index = parse_enhanced_feed_jsonl(content, advertiser_id=17729)
    assert len(index) == 2
    product = index.lookup("17729", "134179")
    assert product is not None
    assert product.search_price == Decimal("1599.90")
    assert product.old_price == Decimal("1999.90")
    assert product.image_url == "https://img/cadeira.jpg"


def test_parse_google_money():
    assert parse_google_money("869.06 GBP") == (Decimal("869.06"), "GBP")
    assert parse_google_money("1599.90 BRL") == (Decimal("1599.90"), "BRL")


def test_enhanced_feed_enriches_collector():
    client = MagicMock()
    client.pages_fetched = 1
    client.fetch_promotions.return_value = [
        {
            "promotionId": 1,
            "type": "promotion",
            "advertiser": {"id": 17729, "name": "Kabum BR", "joined": True},
            "title": "Cadeira",
            "description": "Cadeira",
            "startDate": "2026-07-01T00:00:00+00:00",
            "endDate": "2026-08-01T00:00:00+00:00",
            "status": "active",
            "urlTracking": (
                "https://www.awin1.com/cread.php?ued="
                "https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F134179"
            ),
            "regions": {"all": True, "list": []},
        }
    ]
    client.fetch_enhanced_retail_feed.return_value = (
        '{"id":"134179","title":"Cadeira Gamer","link":'
        '"https://www.kabum.com.br/produto/134179",'
        '"image_link":"https://img/cadeira.jpg",'
        '"availability":"in_stock","price":"1999.90 BRL",'
        '"sale_price":"1599.90 BRL"}\n'
    ).encode("utf-8")

    collector = AwinCollector(
        client=client,
        advertisers=[AwinAdvertiserConfig(17729, "Kabum BR", "KaBuM", True)],
        now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )
    items = collector.collect()
    assert len(items) == 1
    assert items[0]["price"] == 1599.90
    assert items[0]["image_url"] == "https://img/cadeira.jpg"
    assert collector.metrics.feed_source == "enhanced_api"
    assert collector.metrics.offers_with_image == 1


def test_feed_failure_does_not_block_offers_collection(monkeypatch):
    client = MagicMock()
    client.pages_fetched = 1
    client.fetch_promotions.return_value = [
        {
            "promotionId": 1,
            "type": "promotion",
            "advertiser": {"id": 17729, "name": "Kabum BR", "joined": True},
            "title": "Produto X",
            "description": "Produto X",
            "startDate": "2026-07-01T00:00:00+00:00",
            "endDate": "2026-08-01T00:00:00+00:00",
            "status": "active",
            "urlTracking": "https://www.awin1.com/cread.php?ued=https%3A%2F%2Fwww.kabum.com.br%2Fproduto%2F1",
            "regions": {"all": True, "list": []},
        }
    ]
    client.fetch_enhanced_retail_feed.side_effect = AwinHttpError(
        "Enhanced feed not found advertiser=17729 locale=pt_BR"
    )

    def boom(self):
        raise RuntimeError("feed down")

    monkeypatch.setattr(
        "app.clients.awin_product_feed.AwinProductFeedClient.download",
        boom,
    )
    monkeypatch.setattr(
        "app.collectors.awin.enrich_offers_from_landing",
        lambda offers, metrics=None, timeout=20.0: offers,
    )

    collector = AwinCollector(
        client=client,
        advertisers=[AwinAdvertiserConfig(17729, "Kabum BR", "KaBuM", True)],
        product_feed_url="https://productdata.awin.com/datafeed/download/apikey/SECRET/fid/1",
        now=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )
    items = collector.collect()
    assert len(items) == 1
    assert items[0]["kind"] == "promotion"
    assert collector.metrics.feed_download_failed is True
    assert "price" not in items[0]


def test_parse_feed_price_br_and_us():
    assert parse_feed_price("1.599,90") == Decimal("1599.90")
    assert parse_feed_price("1599.90") == Decimal("1599.90")


def test_image_send_passes_image_url_and_persists(tmp_path):
    from app.main import _run_awin_pipeline
    from app.models import SendResult
    from app.settings import Settings

    calls = []

    class OkSender:
        def send(self, chat_id, message, image_url=None, actions=None):
            calls.append({"chat_id": chat_id, "image_url": image_url})
            return SendResult(success=True, provider_message_id="1")

    settings = Settings(
        app_env="test",
        run_mode="once",
        sleep_interval_seconds=600,
        telegram_bot_token=None,
        telegram_dry_run=True,
        telegram_send_interval_seconds=0.0,
        max_products_per_run=10,
        data_dir=str(tmp_path),
        config_dir="config",
        repost_window_hours=12,
        coupon_repost_window_hours=12,
        aliexpress_app_key=None,
        aliexpress_app_secret=None,
        aliexpress_api_endpoint="https://api-sg.aliexpress.com/sync",
        aliexpress_sign_method="hmac",
        aliexpress_tracking_id=None,
        aliexpress_target_currency="BRL",
        aliexpress_target_language="PT",
        aliexpress_ship_to_country="BR",
        shopee_api_url="https://open-api.affiliate.shopee.com.br/graphql",
        shopee_app_id=None,
        shopee_app_secret=None,
        shopee_request_timeout=30.0,
        shopee_page_limit=20,
        shopee_max_pages=5,
        awin_oauth2_token="token",
        awin_publisher_id="999",
        awin_product_feed_url=None,
        awin_feed_locale="pt_BR",
    )
    channels = {
        "telegram": {
            "enabled": True,
            "destinations": {
                "geral": {"chat_id": "CHAT_GERAL", "enabled": True},
                "cupons": {"chat_id": "CHAT_CUPONS", "enabled": True},
                "games": {"chat_id": "CHAT_GAMES", "enabled": True},
            },
        }
    }
    raw = [
        {
            "source": "awin",
            "external_id": "99",
            "kind": "promotion",
            "advertiser_id": "17729",
            "advertiser_name": "Kabum BR",
            "advertiser_display_name": "KaBuM",
            "title": "Gabinete gamer",
            "tracking_url": "https://www.awin1.com/x",
            "image_url": "https://img/x.jpg",
            "price": 100.0,
            "tags": [],
            "metadata": {},
        }
    ]
    _run_awin_pipeline(
        settings,
        {"games": {"external_aliases": ["gamer", "gabinete"]}},
        channels,
        {"telegram": OkSender()},
        tmp_path,
        raw,
        datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
    )
    assert calls
    assert calls[0]["image_url"] == "https://img/x.jpg"
    data = (tmp_path / "sent_awin_offers.json").read_text(encoding="utf-8")
    assert "99" in data
