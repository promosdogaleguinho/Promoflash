from app.models import Promotion
from app.product_identity import (
    build_offer_key,
    build_product_key,
    build_product_price_key,
    normalize_text,
)


def test_normalize_title_removes_generic_terms():
    result = normalize_text("Headphone JBL Promoção Frete Grátis Novo")
    assert "promocao" not in result
    assert "frete-gratis" not in result
    assert "novo" not in result
    assert "headphone-jbl" in result


def test_normalize_removes_accents():
    result = normalize_text("Eletrônicos Açúcar")
    assert "eletronicos" in result
    assert "acucar" in result


def test_build_product_key_with_canonical_id():
    promotion = Promotion(
        external_id="1",
        source="mock",
        title="Headphone JBL",
        url="https://example.com",
        canonical_product_id="jbl-tune-510bt",
    )
    assert build_product_key(promotion) == "mock:product:jbl-tune-510bt"
    assert promotion.product_key == "mock:product:jbl-tune-510bt"


def test_build_product_key_from_title():
    promotion = Promotion(
        external_id="2",
        source="mock",
        title="Smart TV 55 Polegadas",
        url="https://example.com",
    )
    key = build_product_key(promotion)
    assert key.startswith("mock:product-title:")
    assert "smart-tv-55-polegadas" in key


def test_build_offer_key():
    promotion = Promotion(
        external_id="abc-123",
        source="mock",
        title="Produto",
        url="https://example.com",
    )
    assert build_offer_key(promotion) == "mock:offer:abc-123"


def test_build_product_price_key_with_coupon_and_payment():
    promotion = Promotion(
        external_id="3",
        source="mock",
        title="PS5",
        url="https://example.com",
        final_price=3299.00,
        coupon_code="CUPOM10",
        payment_method="pix",
    )
    build_product_key(promotion)
    key = build_product_price_key(promotion)
    assert "329900" in key
    assert "CUPOM10" in key
    assert "pix" in key
