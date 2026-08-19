import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.coupon_config import (
    load_coupon_config,
    load_manual_coupon_campaigns,
    load_manual_product_coupon_bindings,
)


def _campaign_entry(enabled: bool = True, **overrides) -> dict:
    entry = {
        "enabled": enabled,
        "source": "mercadolivre",
        "campaign_id": "c1",
        "title": "Cupom Mercado Livre",
        "campaign_url": "https://secret.example.com/full-url",
        "affiliate_url": "https://secret.example.com/full-url",
        "category": "geral",
        "start_at": "2030-01-10T00:00:00-03:00",
        "coupons": [
            {
                "code": "EX15",
                "discount_type": "percentage",
                "discount_percentage": 15,
                "minimum_spend": 79,
                "maximum_discount": 80,
                "scope_type": "platform",
            }
        ],
    }
    entry.update(overrides)
    return entry


def test_loads_valid_campaign():
    config = {"timezone": "America/Sao_Paulo", "campaigns": [_campaign_entry()]}
    campaigns = load_manual_coupon_campaigns(config)
    assert len(campaigns) == 1
    assert campaigns[0].campaign_id == "c1"


def test_ignores_disabled_campaign():
    config = {"campaigns": [_campaign_entry(enabled=False)]}
    assert load_manual_coupon_campaigns(config) == []


def test_converts_values_to_decimal():
    config = {"campaigns": [_campaign_entry()]}
    coupon = load_manual_coupon_campaigns(config)[0].coupons[0]
    assert coupon.discount_percentage == Decimal("15")
    assert isinstance(coupon.minimum_spend, Decimal)


def test_converts_dates():
    config = {"campaigns": [_campaign_entry()]}
    campaign = load_manual_coupon_campaigns(config)[0]
    assert isinstance(campaign.start_at, datetime)


def test_uses_timezone():
    entry = _campaign_entry(start_at="2030-01-10T00:00:00")
    config = {"timezone": "America/Sao_Paulo", "campaigns": [entry]}
    campaign = load_manual_coupon_campaigns(config)[0]
    assert campaign.start_at.tzinfo is not None


def test_accepts_multiple_coupons():
    entry = _campaign_entry()
    entry["coupons"].append({"code": "EX28", "discount_type": "fixed", "discount_value": 28})
    config = {"campaigns": [entry]}
    assert len(load_manual_coupon_campaigns(config)[0].coupons) == 2


def test_ignores_invalid_entry_without_crashing():
    invalid = {"enabled": True, "source": "shopee"}
    config = {"campaigns": [invalid, _campaign_entry()]}
    campaigns = load_manual_coupon_campaigns(config)
    assert len(campaigns) == 1


def test_loads_product_binding():
    config = {
        "product_bindings": [
            {
                "enabled": True,
                "source": "aliexpress",
                "external_product_id": "PROD1",
                "coupon": {"code": "BIND1", "discount_type": "fixed", "discount_value": 10},
            }
        ]
    }
    bindings = load_manual_product_coupon_bindings(config)
    assert ("aliexpress", "PROD1") in bindings


def test_does_not_modify_file(tmp_path: Path):
    path = tmp_path / "coupons.json"
    payload = {"timezone": "America/Sao_Paulo", "campaigns": [_campaign_entry()]}
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    load_coupon_config(str(tmp_path))

    assert path.read_text(encoding="utf-8") == before


def test_does_not_log_full_url(caplog):
    invalid = {"enabled": True, "source": "shopee", "campaign_url": "https://secret.example.com/full-url"}
    config = {"campaigns": [invalid]}
    with caplog.at_level(logging.WARNING):
        load_manual_coupon_campaigns(config)
    assert "https://secret.example.com/full-url" not in caplog.text
