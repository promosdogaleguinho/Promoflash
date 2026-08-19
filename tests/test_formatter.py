from decimal import Decimal

from app.formatter import format_promotion, format_promotion_message
from app.models import Coupon, CouponDiscountType, FormattedMessage, Promotion


def _fixed_coupon(**kwargs) -> Coupon:
    defaults = {
        "source": "aliexpress",
        "code": "PDF01",
        "discount_type": CouponDiscountType.FIXED,
        "discount_value": Decimal("28"),
        "minimum_spend": Decimal("200"),
    }
    defaults.update(kwargs)
    return Coupon(**defaults)


def _base_promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "1",
        "source": "mock",
        "title": "Produto Teste",
        "url": "https://example.com/produto",
        "store": "Loja Teste",
    }
    defaults.update(kwargs)
    return Promotion(**defaults)


def test_message_with_old_price():
    promotion = _base_promotion(
        price=2199.00,
        final_price=2199.00,
        old_price=2499.00,
        discount_percentage=12.0,
    )
    message = format_promotion_message(promotion)
    assert "De: R$ 2.499,00" in message
    assert "Por: R$ 2.199,00" in message
    assert "Desconto:" not in message


def test_message_without_old_price():
    promotion = _base_promotion(price=199.90, final_price=199.90)
    message = format_promotion_message(promotion)
    assert "Preço: R$ 199,90" in message
    assert "De:" not in message


def test_message_ignores_equal_old_and_final_price():
    promotion = _base_promotion(
        source="aliexpress",
        price=138.88,
        final_price=138.88,
        old_price=138.88,
        store="AliExpress",
    )
    message = format_promotion_message(promotion)
    assert "De:" not in message
    assert "Por:" not in message
    assert "Preço: R$ 138,88" in message


def test_message_with_coupon():
    promotion = _base_promotion(
        price=3299.00,
        final_price=3299.00,
        coupon_code="ALLSITE7DO7",
        price_conditions=["Cupom ALLSITE7DO7", "Pagamento via Pix"],
    )
    message = format_promotion_message(promotion)
    assert "Cupom: ALLSITE7DO7" in message
    assert "- Cupom ALLSITE7DO7" in message


def test_message_with_pix():
    promotion = _base_promotion(
        price=100.00,
        final_price=100.00,
        payment_method="pix",
        requires_pix=True,
    )
    message = format_promotion_message(promotion)
    assert "Pagamento via Pix" in message


def test_uses_affiliate_url():
    promotion = _base_promotion(
        url="https://example.com/original",
        affiliate_url="https://example.com/afiliado",
    )
    message = format_promotion_message(promotion)
    assert "https://example.com/afiliado" in message
    assert "https://example.com/original" not in message


def test_contains_promoflash_bot_brand():
    promotion = _base_promotion()
    message = format_promotion_message(promotion)
    assert "PromoFlash Bot" not in message
    assert "⚡ PromoFlash Bot encontrou" not in message
    assert promotion.title in message


def test_brl_price_formatting():
    promotion = _base_promotion(price=3299.00, final_price=3299.00)
    message = format_promotion_message(promotion)
    assert "R$ 3.299,00" in message


def test_message_without_tags_has_no_tag_line():
    promotion = _base_promotion(price=100.0, final_price=100.0)
    message = format_promotion_message(promotion)
    assert "🏷️" not in message


def test_message_with_tags_shows_tag_line():
    promotion = _base_promotion(
        price=100.0,
        final_price=100.0,
        promotion_tags=["Desconto", "Oferta AliExpress"],
    )
    message = format_promotion_message(promotion)
    assert "🏷️" in message
    assert "Desconto" in message
    assert "Oferta AliExpress" in message


def test_message_with_official_campaign_shows_campaign_name():
    promotion = _base_promotion(
        price=100.0,
        final_price=100.0,
        is_official_campaign=True,
        campaign_name="Choice Day",
        promotion_tags=["Choice Day", "Campanha oficial", "Oferta AliExpress"],
    )
    message = format_promotion_message(promotion)
    assert "Choice Day" in message
    assert "Campanha oficial" in message


def test_aliexpress_message_shows_price_disclaimer():
    promotion = _base_promotion(
        source="aliexpress",
        store="AliExpress",
        price=100.0,
        final_price=100.0,
    )
    message = format_promotion_message(promotion)
    assert "preço sujeito a alteração" in message


def test_non_aliexpress_message_has_no_price_disclaimer():
    promotion = _base_promotion(price=100.0, final_price=100.0)
    message = format_promotion_message(promotion)
    assert "preço sujeito a alteração" not in message


def test_format_promotion_sets_image_url():
    promotion = _base_promotion(
        image_url="https://img.aliexpress.com/produto.jpg",
        price=100.0,
        final_price=100.0,
    )
    result = format_promotion(promotion)

    assert result.image_url == "https://img.aliexpress.com/produto.jpg"


def test_format_promotion_without_image_has_none():
    promotion = _base_promotion(price=100.0, final_price=100.0)
    result = format_promotion(promotion)

    assert result.image_url is None


def test_format_promotion_returns_formatted_message():
    promotion = _base_promotion(
        affiliate_url="https://s.click.aliexpress.com/e/afiliado",
        price=100.0,
        final_price=100.0,
    )
    result = format_promotion(promotion)

    assert isinstance(result, FormattedMessage)
    assert result.offer_url == "https://s.click.aliexpress.com/e/afiliado"
    assert result.button_text == "🛒 Ver oferta"


def test_format_promotion_prioritizes_affiliate_url_as_offer_url():
    promotion = _base_promotion(
        url="https://example.com/original",
        affiliate_url="https://example.com/afiliado",
        price=100.0,
        final_price=100.0,
    )
    result = format_promotion(promotion)

    assert result.offer_url == "https://example.com/afiliado"


def test_format_promotion_text_has_no_link_when_offer_url_exists():
    promotion = _base_promotion(
        affiliate_url="https://example.com/afiliado",
        price=100.0,
        final_price=100.0,
    )
    result = format_promotion(promotion)

    assert "https://example.com/afiliado" not in result.text
    assert "Ver oferta:" not in result.text


def test_format_promotion_aliexpress_keeps_price_disclaimer():
    promotion = _base_promotion(
        source="aliexpress",
        store="AliExpress",
        affiliate_url="https://s.click.aliexpress.com/e/afiliado",
        price=134.45,
        final_price=134.45,
        old_price=292.28,
        discount_percentage=54.0,
    )
    result = format_promotion(promotion)

    assert "preço sujeito a alteração" in result.text
    assert "De: R$ 292,28" in result.text
    assert "Por: R$ 134,45" in result.text


def test_format_promotion_without_offer_url_falls_back_to_text_link():
    promotion = _base_promotion(
        url="",
        affiliate_url=None,
        price=100.0,
        final_price=100.0,
    )
    result = format_promotion(promotion)

    assert result.offer_url is None
    assert "Ver oferta:" not in result.text


def test_promotion_with_coupon_shows_code():
    promotion = _base_promotion(price=210.0, final_price=210.0, coupons=[_fixed_coupon()])
    message = format_promotion_message(promotion)
    assert "🎟️ Cupom: PDF01" in message


def test_coupon_without_code_shows_available():
    promotion = _base_promotion(
        price=210.0, final_price=210.0, coupons=[_fixed_coupon(code=None)]
    )
    message = format_promotion_message(promotion)
    assert "🎟️ Cupom disponível" in message


def test_fixed_discount_is_formatted():
    promotion = _base_promotion(price=210.0, final_price=210.0, coupons=[_fixed_coupon()])
    message = format_promotion_message(promotion)
    assert "R$ 28 OFF em compras a partir de R$ 200" in message


def test_percentage_discount_is_formatted():
    coupon = Coupon(
        source="mercadolivre",
        code="MELI15",
        discount_type=CouponDiscountType.PERCENTAGE,
        discount_percentage=Decimal("15"),
        minimum_spend=Decimal("79"),
        maximum_discount=Decimal("80"),
    )
    promotion = _base_promotion(price=100.0, final_price=100.0, coupons=[coupon])
    message = format_promotion_message(promotion)
    assert "15% OFF em compras a partir de R$ 79" in message
    assert "Limite de R$ 80 de desconto" in message


def test_app_only_indicator():
    promotion = _base_promotion(
        price=210.0, final_price=210.0, coupons=[_fixed_coupon(app_only=True)]
    )
    message = format_promotion_message(promotion)
    assert "📱 Exclusivo no app" in message


def test_coins_indicator():
    promotion = _base_promotion(
        price=210.0,
        final_price=210.0,
        coupons=[_fixed_coupon(requires_coins=True, coins_amount=442)],
    )
    message = format_promotion_message(promotion)
    assert "🪙 Use também 442 moedas no app" in message


def test_requires_activation_condition():
    promotion = _base_promotion(
        price=210.0, final_price=210.0, coupons=[_fixed_coupon(requires_activation=True)]
    )
    message = format_promotion_message(promotion)
    assert "🎟️ Requer ativação ou resgate" in message


def test_does_not_compute_final_price_with_coupon():
    promotion = _base_promotion(price=210.0, final_price=210.0, coupons=[_fixed_coupon()])
    message = format_promotion_message(promotion)
    assert "Preço: R$ 210,00" in message
    assert "R$ 182" not in message


def test_shows_at_most_two_coupons():
    coupons = [
        _fixed_coupon(code="A", discount_value=Decimal("10")),
        _fixed_coupon(code="B", discount_value=Decimal("20")),
        _fixed_coupon(code="C", discount_value=Decimal("30")),
    ]
    promotion = _base_promotion(price=210.0, final_price=210.0, coupons=coupons)
    message = format_promotion_message(promotion)
    assert message.count("🎟️ Cupom:") == 2
    assert "Outros cupons podem estar disponíveis na página da oferta." in message


def test_creates_product_button():
    promotion = _base_promotion(
        affiliate_url="https://p", price=210.0, final_price=210.0, coupons=[_fixed_coupon()]
    )
    result = format_promotion(promotion)
    assert result.actions[0].action_type == "product"
    assert result.actions[0].text == "🛒 Ver produto"


def test_creates_coupon_button_when_url_differs():
    coupon = _fixed_coupon(affiliate_url="https://coupon")
    promotion = _base_promotion(
        affiliate_url="https://p", price=210.0, final_price=210.0, coupons=[coupon]
    )
    result = format_promotion(promotion)
    coupon_actions = [a for a in result.actions if a.action_type == "coupon"]
    assert len(coupon_actions) == 1
    assert coupon_actions[0].url == "https://coupon"


def test_does_not_duplicate_button_when_url_equal():
    coupon = _fixed_coupon(affiliate_url="https://p")
    promotion = _base_promotion(
        affiliate_url="https://p", price=210.0, final_price=210.0, coupons=[coupon]
    )
    result = format_promotion(promotion)
    assert len(result.actions) == 1


def test_message_shows_at_most_three_tags():
    promotion = _base_promotion(
        price=100.0,
        final_price=100.0,
        campaign_name="Choice Day",
        promotion_tags=[
            "Choice Day",
            "Campanha oficial",
            "Desconto",
            "Mais vendido",
            "Oferta AliExpress",
        ],
    )
    message = format_promotion_message(promotion)
    tag_line = next(line for line in message.splitlines() if line.startswith("🏷️"))
    parts = tag_line.replace("🏷️ ", "").split(" • ")
    assert len(parts) == 3
