from datetime import datetime, timezone
from decimal import Decimal

from app.collectors.shopee_mapper import (
    PERIOD_OPEN_ENDED_SENTINEL,
    derive_shop_tier,
    map_shopee_product,
    to_decimal,
)
from app.formatter import format_promotion_message
from app.normalizer import normalize
from app.promotion_quality import apply_promotion_quality


NOW = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)


def _node(**overrides) -> dict:
    base = {
        "itemId": 58262957321,
        "productName": "Fone Bluetooth Premium",
        "commissionRate": "0.08",
        "commission": "4.00",
        "appExistRate": "0.05",
        "appNewRate": "0.06",
        "webExistRate": "0.04",
        "webNewRate": "0.05",
        "price": "49.99",
        "priceMin": "49.99",
        "priceMax": "49.99",
        "priceDiscountRate": "20",
        "sales": 120,
        "imageUrl": "https://cf.shopee.com.br/file/example.jpg",
        "shopName": "Loja Exemplo",
        "shopId": 1314145794,
        "shopType": [],
        "productLink": "https://shopee.com.br/product/1314145794/58262957321",
        "offerLink": "https://s.shopee.com.br/offer-abc",
        "periodStartTime": 1700000000,
        "periodEndTime": PERIOD_OPEN_ENDED_SENTINEL,
        "productCatIds": [1001, 0, 2002],
        "ratingStar": "4.8",
        "sellerCommissionRate": "0.05",
        "shopeeCommissionRate": "0.03",
    }
    base.update(overrides)
    return base


def test_identity_by_shop_and_item():
    mapped = map_shopee_product(_node(), now=NOW)
    assert mapped is not None
    assert mapped["external_id"] == "1314145794:58262957321"
    assert mapped["canonical_product_id"] == "1314145794:58262957321"
    assert mapped["source"] == "shopee"


def test_price_from_price_field():
    mapped = map_shopee_product(
        _node(price="59.90", priceMin="40.00", priceMax="80.00"),
        now=NOW,
    )
    assert mapped["final_price"] == 59.90


def test_fallback_to_price_min():
    mapped = map_shopee_product(
        _node(price=None, priceMin="35.50", priceMax="35.50"),
        now=NOW,
    )
    assert mapped is not None
    assert mapped["final_price"] == 35.50


def test_product_without_price_rejected():
    assert map_shopee_product(_node(price=None, priceMin=None), now=NOW) is None


def test_single_price_and_range():
    single = map_shopee_product(
        _node(priceMin="49.99", priceMax="49.99"),
        now=NOW,
    )
    ranged = map_shopee_product(
        _node(price="49.99", priceMin="49.99", priceMax="89.99"),
        now=NOW,
    )
    assert single["metadata"]["has_price_range"] is False
    assert ranged["metadata"]["has_price_range"] is True


def test_large_range_not_blocked():
    mapped = map_shopee_product(
        _node(price="10.00", priceMin="10.00", priceMax="999.00"),
        now=NOW,
    )
    assert mapped is not None


def test_discount_zero_rejected():
    assert map_shopee_product(_node(priceDiscountRate="0"), now=NOW) is None


def test_discount_positive_accepted():
    mapped = map_shopee_product(_node(priceDiscountRate="15"), now=NOW)
    assert mapped is not None
    assert mapped["discount_percentage"] == 15.0
    assert mapped["old_price"] == 58.81
    assert mapped["metadata"]["original_price_estimated"] is True


def test_discount_fraction_normalized():
    mapped = map_shopee_product(
        _node(price="80.00", priceMin="80.00", priceMax="80.00", priceDiscountRate="0.20"),
        now=NOW,
    )
    assert mapped is not None
    assert mapped["discount_percentage"] == 20.0
    assert mapped["old_price"] == 100.0


def test_commission_and_rating_as_string():
    mapped = map_shopee_product(
        _node(commission="3.50", commissionRate="0.07", ratingStar="4.5"),
        now=NOW,
    )
    assert mapped["metadata"]["commission"] == "3.50"
    assert mapped["metadata"]["commission_rate"] == "0.07"
    assert mapped["rating"] == 4.5
    assert isinstance(to_decimal(mapped["metadata"]["commission"]), Decimal)


def test_optional_null_fields():
    mapped = map_shopee_product(
        _node(
            commission=None,
            ratingStar=None,
            sales=None,
            imageUrl=None,
            shopName=None,
        ),
        now=NOW,
    )
    assert mapped is not None
    assert mapped["rating"] is None
    assert mapped["sales"] is None


def test_shop_types():
    assert derive_shop_tier([]) == "standard"
    assert derive_shop_tier([1]) == "mall"
    assert derive_shop_tier([2]) == "star"
    assert derive_shop_tier([4]) == "star_plus"
    assert derive_shop_tier([2, 4]) == "star_plus"
    assert derive_shop_tier([1, 4]) == "mall"

    mall = map_shopee_product(_node(shopType=[1]), now=NOW)
    star = map_shopee_product(_node(shopType=[2]), now=NOW)
    star_plus = map_shopee_product(_node(shopType=[4]), now=NOW)
    multi = map_shopee_product(_node(shopType=[2, 4]), now=NOW)
    empty = map_shopee_product(_node(shopType=[]), now=NOW)

    assert mall["metadata"]["shop_tier"] == "mall"
    assert star["metadata"]["shop_tier"] == "star"
    assert star_plus["metadata"]["shop_tier"] == "star_plus"
    assert multi["metadata"]["shop_tier"] == "star_plus"
    assert empty["metadata"]["shop_tier"] == "standard"
    assert mall["is_official_store"] is True


def test_product_cat_ids_with_zero():
    mapped = map_shopee_product(_node(productCatIds=[1001, 0, 2002]), now=NOW)
    assert mapped["metadata"]["product_cat_ids"] == [1001, 0, 2002]
    assert mapped["metadata"]["classification_cat_ids"] == [1001, 2002]


def test_period_open_ended_sentinel():
    mapped = map_shopee_product(
        _node(periodEndTime=PERIOD_OPEN_ENDED_SENTINEL),
        now=NOW,
    )
    assert mapped["metadata"]["period_end_at"] is None
    assert mapped["metadata"]["period_open_ended"] is True


def test_period_expired_rejected():
    assert (
        map_shopee_product(
            _node(periodStartTime=1700000000, periodEndTime=1700000001),
            now=NOW,
        )
        is None
    )


def test_period_future_start_rejected():
    future = int(datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp())
    assert (
        map_shopee_product(
            _node(periodStartTime=future, periodEndTime=PERIOD_OPEN_ENDED_SENTINEL),
            now=NOW,
        )
        is None
    )


def test_period_with_real_end_accepted():
    end = int(datetime(2026, 12, 31, tzinfo=timezone.utc).timestamp())
    mapped = map_shopee_product(
        _node(periodStartTime=1700000000, periodEndTime=end),
        now=NOW,
    )
    assert mapped is not None
    assert mapped["metadata"]["period_open_ended"] is False
    assert mapped["metadata"]["period_end_at"] is not None


def test_offer_link_required():
    assert map_shopee_product(_node(offerLink=None), now=NOW) is None
    assert map_shopee_product(_node(offerLink=""), now=NOW) is None


def test_offer_link_present_sets_affiliate_url():
    mapped = map_shopee_product(_node(), now=NOW)
    assert mapped["affiliate_url"] == "https://s.shopee.com.br/offer-abc"
    assert mapped["url"] == "https://s.shopee.com.br/offer-abc"
    assert mapped["metadata"]["product_link"].startswith("https://shopee.com.br/")


def test_message_single_price_and_from_price():
    single = normalize([map_shopee_product(_node(), now=NOW)])[0]
    apply_promotion_quality(single)
    single_msg = format_promotion_message(single, now=NOW)
    assert "De: R$ 62,49" in single_msg
    assert "Por: R$ 49,99" in single_msg
    assert "Desconto:" not in single_msg
    assert "commission" not in single_msg.lower()
    assert "Variação" not in single_msg
    assert "0.08" not in single_msg

    ranged = normalize(
        [
            map_shopee_product(
                _node(price="49.99", priceMin="49.99", priceMax="89.99"),
                now=NOW,
            )
        ]
    )[0]
    apply_promotion_quality(ranged)
    ranged_msg = format_promotion_message(ranged, now=NOW)
    assert "De: R$ 62,49" in ranged_msg
    assert "Por: A partir de R$ 49,99" in ranged_msg
    assert "89,99" not in ranged_msg
    assert "Variação" not in ranged_msg
