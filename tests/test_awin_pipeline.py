import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from app.awin_formatter import format_campaign_offer
from app.awin_persistence import AwinOfferPersistence
from app.awin_repost_policy import (
    build_offer_fingerprint,
    build_offer_snapshot,
    should_send_offer_to_destination,
)
from app.category_resolver import resolve_campaign_offer_category
from app.main import _run_awin_pipeline
from app.models import CampaignOffer, SendResult
from app.router import route_campaign_offer
from app.settings import Settings


CHANNELS = {
    "telegram": {
        "enabled": True,
        "destinations": {
            "geral": {"chat_id": "CHAT_GERAL", "enabled": True},
            "eletronicos": {"chat_id": "CHAT_ELEC", "enabled": True},
            "games": {"chat_id": "CHAT_GAMES", "enabled": True},
            "cupons": {"chat_id": "CHAT_CUPONS", "enabled": True},
        },
    },
    "whatsapp": {"enabled": False, "destinations": {}},
}

CATEGORIES = {
    "eletronicos": {"external_aliases": ["notebook", "monitor"]},
    "games": {"external_aliases": ["gamer", "playstation", "nintendo"]},
    "casa": {"external_aliases": ["aspirador", "mesa"]},
}


def _offer(**overrides) -> CampaignOffer:
    data = {
        "source": "awin",
        "external_id": "4024269",
        "kind": "voucher",
        "advertiser_id": "17729",
        "advertiser_name": "Kabum BR",
        "advertiser_display_name": "KaBuM",
        "title": "Cupom gamer",
        "tracking_url": "https://www.awin1.com/x",
        "coupon_code": "CODE10",
        "description": None,
        "status": "active",
    }
    data.update(overrides)
    return CampaignOffer(**data)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
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


def test_voucher_routes_to_cupons_and_category():
    destinations = route_campaign_offer("voucher", "games", CHANNELS)
    cats = {d["category"] for d in destinations}
    assert cats == {"cupons", "games"}
    assert "geral" not in cats


def test_voucher_without_category_routes_to_cupons_and_geral():
    destinations = route_campaign_offer("voucher", "geral", CHANNELS)
    cats = {d["category"] for d in destinations}
    assert cats == {"cupons", "geral"}


def test_promotion_routes_to_category_not_cupons():
    destinations = route_campaign_offer("promotion", "eletronicos", CHANNELS)
    assert len(destinations) == 1
    assert destinations[0]["category"] == "eletronicos"


def test_promotion_without_category_routes_to_geral():
    destinations = route_campaign_offer("promotion", "geral", CHANNELS)
    assert destinations[0]["category"] == "geral"
    assert all(d["category"] != "cupons" for d in destinations)


def test_categorization_uses_resolver():
    offer = _offer(title="Notebook gamer com SSD", kind="promotion", coupon_code=None)
    category = resolve_campaign_offer_category(offer, CATEGORIES)
    assert category == "eletronicos"
    assert offer.resolved_category == "eletronicos"


def test_formatter_voucher_and_promotion_use_tracking_url():
    voucher = format_campaign_offer(_offer())
    assert "Cupom KaBuM" in voucher.text
    assert "Cupom: CODE10" in voucher.text
    assert "https://www.awin1.com/x" not in voucher.text
    assert voucher.offer_url == "https://www.awin1.com/x"
    assert voucher.actions[0].url == "https://www.awin1.com/x"
    assert voucher.image_url is None

    promotion = format_campaign_offer(
        _offer(kind="promotion", coupon_code=None, title="Cadeira gamer")
    )
    assert "Oferta KaBuM" in promotion.text
    assert "Cupom:" not in promotion.text
    assert "https://www.awin1.com/x" not in promotion.text
    assert promotion.offer_url == "https://www.awin1.com/x"
    assert promotion.actions[0].text == "🔥 Ver oferta"
    assert promotion.actions[0].url == "https://www.awin1.com/x"


def test_persistence_and_antirepost_per_destination(tmp_path: Path):
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    offer = _offer()
    persistence = AwinOfferPersistence(str(tmp_path / "sent_awin_offers.json"))
    snapshots = []

    assert should_send_offer_to_destination(offer, "cupons", snapshots, now)
    snap = build_offer_snapshot(offer, "cupons", now)
    persistence.add_snapshot(snap)
    snapshots = persistence.load_snapshots()

    assert not should_send_offer_to_destination(offer, "cupons", snapshots, now)
    assert should_send_offer_to_destination(offer, "games", snapshots, now)

    changed = _offer(title="Cupom gamer atualizado")
    assert build_offer_fingerprint(changed) != build_offer_fingerprint(offer)
    assert not should_send_offer_to_destination(changed, "cupons", snapshots, now)

    later = now + timedelta(hours=25)
    assert should_send_offer_to_destination(changed, "cupons", snapshots, later)


def test_pipeline_destination_failure_isolation(tmp_path: Path):
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    sender = MagicMock()
    sender.send.side_effect = [
        SendResult(success=True, provider_message_id="1"),
        SendResult(success=False, error="boom"),
    ]
    raw_items = [
        {
            "source": "awin",
            "external_id": "1",
            "kind": "voucher",
            "advertiser_id": "17729",
            "advertiser_name": "Kabum BR",
            "advertiser_display_name": "KaBuM",
            "title": "Controle playstation em oferta",
            "tracking_url": "https://www.awin1.com/x",
            "coupon_code": "CODE10",
            "description": None,
            "status": "active",
            "tags": [],
            "metadata": {},
        }
    ]

    _run_awin_pipeline(
        _settings(tmp_path),
        CATEGORIES,
        CHANNELS,
        {"telegram": sender},
        tmp_path,
        raw_items,
        now,
    )

    assert sender.send.call_count == 2
    data = json.loads((tmp_path / "sent_awin_offers.json").read_text(encoding="utf-8"))
    destinations = {item["destination"] for item in data["sent_awin_offers"]}
    assert destinations == {"cupons"}
