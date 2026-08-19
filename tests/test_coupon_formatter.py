from datetime import datetime
from decimal import Decimal

from app.coupon_formatter import format_coupon_campaign
from app.coupon_lifecycle import get_timezone
from app.models import Coupon, CouponCampaign, CouponDiscountType

TZ = get_timezone("America/Sao_Paulo")
NOW = datetime(2030, 1, 12, 12, 0, tzinfo=TZ)


def _percentage_coupon(code: str | None = "EX15") -> Coupon:
    return Coupon(
        source="mercadolivre",
        code=code,
        discount_type=CouponDiscountType.PERCENTAGE,
        discount_percentage=Decimal("15"),
        minimum_spend=Decimal("79"),
        maximum_discount=Decimal("80"),
    )


def _campaign(**overrides) -> CouponCampaign:
    data = {
        "source": "mercadolivre",
        "campaign_id": "c1",
        "title": "Cupom Mercado Livre",
        "coupons": [_percentage_coupon()],
        "affiliate_url": "https://aff.example.com",
    }
    data.update(overrides)
    return CouponCampaign(**data)


def test_single_coupon_campaign():
    message = format_coupon_campaign(_campaign(), NOW)
    assert "🎟️ Cupom Mercado Livre" in message.text
    assert "15% OFF em compras a partir de R$ 79" in message.text
    assert "Limite de R$ 80 de desconto" in message.text
    assert "Código: EX15" in message.text


def test_multi_coupon_campaign():
    coupons = [
        Coupon(
            source="aliexpress",
            code="EX01",
            discount_type=CouponDiscountType.FIXED,
            discount_value=Decimal("12"),
            minimum_spend=Decimal("90"),
        ),
        Coupon(
            source="aliexpress",
            code="EX02",
            discount_type=CouponDiscountType.FIXED,
            discount_value=Decimal("28"),
            minimum_spend=Decimal("200"),
        ),
    ]
    campaign = _campaign(source="aliexpress", title="Novo evento AliExpress", coupons=coupons)
    message = format_coupon_campaign(campaign, NOW)
    assert "🔥 Novo evento AliExpress" in message.text
    assert "Cupons do evento:" in message.text
    assert "🎟️ R$ 12 OFF em compras a partir de R$ 90" in message.text
    assert "Código: EX01" in message.text
    assert "Código: EX02" in message.text


def test_future_campaign_midnight():
    campaign = _campaign(start_at=datetime(2030, 1, 20, 0, 0, tzinfo=TZ))
    message = format_coupon_campaign(campaign, NOW)
    assert "Começa à meia-noite." in message.text


def test_future_campaign_specific_time_has_no_midnight_phrase():
    campaign = _campaign(start_at=datetime(2030, 1, 20, 9, 30, tzinfo=TZ))
    message = format_coupon_campaign(campaign, NOW)
    assert "Começa à meia-noite." not in message.text
    assert "Começa em 20/01/2030 às 09:30." in message.text


def test_validity_is_displayed():
    campaign = _campaign(end_at=datetime(2030, 1, 15, 23, 59, tzinfo=TZ))
    message = format_coupon_campaign(campaign, NOW)
    assert "Válido até 15/01/2030 às 23:59." in message.text


def test_empty_fields_do_not_appear():
    message = format_coupon_campaign(_campaign(description=None), NOW)
    assert "None" not in message.text


def test_campaign_creates_primary_action():
    message = format_coupon_campaign(_campaign(), NOW)
    assert len(message.actions) == 1


def test_uses_affiliate_url_before_campaign_url():
    campaign = _campaign(
        affiliate_url="https://aff.example.com",
        campaign_url="https://camp.example.com",
    )
    message = format_coupon_campaign(campaign, NOW)
    assert message.actions[0].url == "https://aff.example.com"


def test_campaign_without_url_does_not_break():
    campaign = _campaign(affiliate_url=None)
    campaign.coupons = [_percentage_coupon()]
    message = format_coupon_campaign(campaign, NOW)
    assert message.actions == []


def test_coupon_without_code_is_formatted():
    campaign = _campaign(coupons=[_percentage_coupon(code=None)])
    message = format_coupon_campaign(campaign, NOW)
    assert "Código:" not in message.text
    assert "15% OFF" in message.text


def test_app_conditions_appear():
    coupon = _percentage_coupon()
    coupon.app_only = True
    campaign = _campaign(coupons=[coupon])
    message = format_coupon_campaign(campaign, NOW)
    assert "📱 Exclusivo no app" in message.text


def test_coins_appear():
    coupon = _percentage_coupon()
    coupon.requires_coins = True
    coupon.coins_amount = 442
    campaign = _campaign(coupons=[coupon])
    message = format_coupon_campaign(campaign, NOW)
    assert "442 moedas" in message.text


def test_codes_display_correctly():
    message = format_coupon_campaign(_campaign(), NOW)
    assert "Código: EX15" in message.text


def test_internal_metadata_not_in_message():
    coupon = _percentage_coupon()
    coupon.metadata["attachment_reason"] = "manual_campaign"
    campaign = _campaign(coupons=[coupon])
    message = format_coupon_campaign(campaign, NOW)
    assert "attachment_reason" not in message.text
