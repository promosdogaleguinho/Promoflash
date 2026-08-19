from datetime import datetime, timedelta, timezone

from app.collectors.awin_mapper import (
    AwinAdvertiserConfig,
    map_awin_offer,
)
from app.text_encoding import fix_mojibake

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
ADVERTISERS = {
    17729: AwinAdvertiserConfig(
        id=17729,
        name="Kabum BR",
        display_name="KaBuM",
        enabled=True,
    )
}


def _base_offer(**overrides):
    payload = {
        "promotionId": 4024269,
        "type": "voucher",
        "advertiser": {"id": 17729, "name": "Kabum BR", "joined": True},
        "title": "10% OFF em produtos gamer",
        "description": "10% OFF em produtos gamer",
        "startDate": (NOW - timedelta(hours=1)).isoformat(),
        "endDate": (NOW + timedelta(hours=12)).isoformat(),
        "status": "active",
        "urlTracking": "https://www.awin1.com/cread.php?x",
        "regions": {"all": False, "list": [{"countryCode": "BR"}]},
        "voucher": {"code": "JULHOGAMER10", "exclusive": False},
    }
    payload.update(overrides)
    return payload


def test_map_voucher_success():
    mapped, reason = map_awin_offer(_base_offer(), ADVERTISERS, NOW)
    assert reason is None
    assert mapped is not None
    assert mapped["kind"] == "voucher"
    assert mapped["coupon_code"] == "JULHOGAMER10"
    assert mapped["advertiser_display_name"] == "KaBuM"
    assert mapped["tracking_url"].startswith("https://www.awin1.com")
    assert mapped["description"] is None


def test_map_promotion_without_price_or_image():
    mapped, reason = map_awin_offer(
        _base_offer(type="promotion", voucher=None, promotionId=99),
        ADVERTISERS,
        NOW,
    )
    assert reason is None
    assert mapped["kind"] == "promotion"
    assert mapped["coupon_code"] is None
    assert mapped.get("image_url") is None
    assert mapped.get("price") is None


def test_reject_advertiser_not_enabled():
    advertisers = {
        17729: AwinAdvertiserConfig(17729, "Kabum BR", "KaBuM", enabled=False)
    }
    mapped, reason = map_awin_offer(_base_offer(), advertisers, NOW)
    assert mapped is None
    assert reason == "advertiser_not_enabled"


def test_reject_joined_false():
    mapped, reason = map_awin_offer(
        _base_offer(advertiser={"id": 17729, "name": "Kabum BR", "joined": False}),
        ADVERTISERS,
        NOW,
    )
    assert mapped is None
    assert reason == "advertiser_not_joined"


def test_reject_outside_date_window():
    mapped, reason = map_awin_offer(
        _base_offer(
            startDate=(NOW + timedelta(days=1)).isoformat(),
            endDate=(NOW + timedelta(days=2)).isoformat(),
        ),
        ADVERTISERS,
        NOW,
    )
    assert mapped is None
    assert reason == "outside_date_window"


def test_accept_expiring_soon():
    mapped, reason = map_awin_offer(
        _base_offer(status="expiringSoon"),
        ADVERTISERS,
        NOW,
    )
    assert reason is None
    assert mapped["status"] == "expiringSoon"


def test_accept_active():
    mapped, reason = map_awin_offer(_base_offer(status="active"), ADVERTISERS, NOW)
    assert reason is None
    assert mapped["status"] == "active"


def test_reject_voucher_without_code():
    mapped, reason = map_awin_offer(
        _base_offer(voucher={"code": "", "exclusive": False}),
        ADVERTISERS,
        NOW,
    )
    assert mapped is None
    assert reason == "missing_voucher_code"


def test_api_dates_prevail_over_title_text():
    mapped, reason = map_awin_offer(
        _base_offer(title="PromoÃ§Ã£o relÃ¢mpago sÃ³ hoje"),
        ADVERTISERS,
        NOW,
    )
    assert reason is None
    assert "relâmpago" in mapped["title"]


def test_fix_mojibake_conservative():
    assert fix_mojibake("AtÃ©") == "Até"
    assert fix_mojibake("promoÃ§Ã£o") == "promoção"
    assert fix_mojibake("acessÃ³rios") == "acessórios"
    assert fix_mojibake("texto válido") == "texto válido"
    assert fix_mojibake(None) is None
