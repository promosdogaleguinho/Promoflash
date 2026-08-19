from app.models import Coupon, Promotion
from app.offer_ranker import rank_offer, select_best_offer


def _promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "1",
        "source": "mock",
        "title": "Produto",
        "url": "https://example.com",
    }
    defaults.update(kwargs)
    return Promotion(**defaults)


def test_same_score_lower_price_wins():
    cheap = _promotion(external_id="cheap", final_price=100.0, promotion_score=20)
    expensive = _promotion(
        external_id="expensive", final_price=200.0, promotion_score=20
    )
    assert select_best_offer([expensive, cheap]).external_id == "cheap"


def test_higher_relevance_score_beats_cheaper_junk():
    valuable = _promotion(
        external_id="valuable",
        final_price=200.0,
        promotion_score=80,
        discount_percentage=25.0,
    )
    cheap = _promotion(
        external_id="cheap",
        final_price=40.0,
        promotion_score=5,
        discount_percentage=5.0,
    )
    assert select_best_offer([valuable, cheap]).external_id == "valuable"


def test_official_store_bonus():
    regular = _promotion(
        external_id="regular",
        final_price=100.0,
        promotion_score=10,
        is_official_store=False,
    )
    official = _promotion(
        external_id="official",
        final_price=105.0,
        promotion_score=10,
        is_official_store=True,
    )
    assert rank_offer(official) > rank_offer(regular)


def test_free_shipping_bonus():
    without = _promotion(
        external_id="without",
        final_price=100.0,
        promotion_score=10,
        free_shipping=False,
    )
    with_shipping = _promotion(
        external_id="with",
        final_price=102.0,
        promotion_score=10,
        free_shipping=True,
    )
    assert rank_offer(with_shipping) > rank_offer(without)


def test_modern_coupon_collection_receives_coupon_bonus():
    without = _promotion(external_id="without", final_price=100.0, promotion_score=10)
    with_coupon = _promotion(
        external_id="with",
        final_price=100.0,
        promotion_score=10,
        coupons=[Coupon(source="aliexpress", code="SAVE10")],
    )
    assert rank_offer(with_coupon) > rank_offer(without)
