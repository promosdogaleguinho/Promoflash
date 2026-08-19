from datetime import datetime, timedelta, timezone

from app.models import Promotion
from app.promotion_quality import (
    apply_promotion_quality,
    calculate_discount_percentage,
    calculate_promotion_score,
    is_publishable_promotion,
)


def _promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "1",
        "source": "aliexpress",
        "title": "Produto Teste",
        "url": "https://example.com/produto",
        "affiliate_url": "https://s.click.aliexpress.com/e/produto",
        "final_price": 100.0,
    }
    defaults.update(kwargs)
    return Promotion(**defaults)


def test_rejects_product_without_price():
    promotion = _promotion(final_price=None, price=None)
    assert is_publishable_promotion(promotion) is False


def test_rejects_product_without_positive_price():
    promotion = _promotion(final_price=0, price=0)
    assert is_publishable_promotion(promotion) is False


def test_rejects_product_without_affiliate_link():
    promotion = _promotion(url="https://example.com", affiliate_url=None)
    assert is_publishable_promotion(promotion) is False


def test_rejects_product_without_title():
    promotion = _promotion(title="")
    assert is_publishable_promotion(promotion) is False


def test_approves_basic_publishable_product():
    promotion = _promotion(discount_percentage=5.0, old_price=110.0, sales=1)
    assert is_publishable_promotion(promotion) is True


def test_approves_small_discount_product():
    promotion = _promotion(
        source="mock",
        discount_percentage=1.0,
        old_price=101.0,
        sales=1,
    )
    assert is_publishable_promotion(promotion) is True


def test_rejects_aliexpress_without_real_price_drop():
    promotion = _promotion(
        source="aliexpress",
        discount_percentage=0.0,
        old_price=100.0,
        final_price=100.0,
        is_official_campaign=True,
        campaign_name="Envio do Brasil",
    )
    assert is_publishable_promotion(promotion) is False


def test_rejects_shopee_without_discount():
    promotion = _promotion(
        source="shopee",
        external_id="1314145794:58262957321",
        discount_percentage=0.0,
        sales=5,
    )
    assert is_publishable_promotion(promotion) is False


def test_approves_shopee_with_small_discount():
    promotion = _promotion(
        source="shopee",
        external_id="1314145794:58262957321",
        discount_percentage=5.0,
        sales=5,
    )
    assert is_publishable_promotion(promotion) is True


def test_rejects_shopee_without_shop_item_identity():
    promotion = _promotion(source="shopee", external_id="only-item")
    assert is_publishable_promotion(promotion) is False


def test_rejects_not_started_period():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    promotion = _promotion(
        source="shopee",
        external_id="1:2",
        metadata={"period_start_at": future},
    )
    assert is_publishable_promotion(promotion) is False


def test_rejects_expired_period():
    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    promotion = _promotion(
        source="shopee",
        external_id="1:2",
        metadata={"period_end_at": past},
    )
    assert is_publishable_promotion(promotion) is False


def test_campaign_name_adds_tag():
    promotion = _promotion(campaign_name="Super Deals", is_official_campaign=True)
    apply_promotion_quality(promotion)
    assert "Super Deals" in promotion.promotion_tags
    assert "Campanha oficial" in promotion.promotion_tags


def test_no_duplicate_tags():
    promotion = _promotion(
        source="aliexpress",
        campaign_name="Choice Day",
        promotion_tags=["Choice Day", "Oferta AliExpress"],
    )
    apply_promotion_quality(promotion)
    assert promotion.promotion_tags.count("Choice Day") == 1
    assert promotion.promotion_tags.count("Oferta AliExpress") == 1


def test_shopee_tag_added():
    promotion = _promotion(source="shopee", external_id="1:2")
    apply_promotion_quality(promotion)
    assert "Oferta Shopee" in promotion.promotion_tags


def test_promotion_score_is_filled():
    promotion = _promotion(discount_percentage=30.0)
    apply_promotion_quality(promotion)
    assert promotion.promotion_score is not None
    assert promotion.promotion_score > 0


def test_discount_calculated_when_missing():
    promotion = _promotion(final_price=80.0, old_price=100.0, discount_percentage=None)
    apply_promotion_quality(promotion)
    assert promotion.discount_percentage == 20.0


def test_calculate_discount_percentage_rules():
    assert calculate_discount_percentage(None, 100.0) is None
    assert calculate_discount_percentage(100.0, None) is None
    assert calculate_discount_percentage(100.0, 100.0) is None
    assert calculate_discount_percentage(100.0, 80.0) is None
    assert calculate_discount_percentage(80.0, 100.0) == 20.0


def test_score_bonus_for_official_campaign():
    common = _promotion()
    official = _promotion(is_official_campaign=True, campaign_name="Black Friday")
    assert calculate_promotion_score(official) > calculate_promotion_score(common)
