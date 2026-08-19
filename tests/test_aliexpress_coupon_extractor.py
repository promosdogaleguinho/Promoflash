from decimal import Decimal

from app.collectors.aliexpress_coupon_extractor import extract_aliexpress_coupons
from app.models import CouponDiscountType


def test_extracts_official_promo_code_info_fields():
    coupons = extract_aliexpress_coupons(
        {
            "product_id": "1",
            "promo_code_info": {
                "promo_code": "GMG20207",
                "code_value": "On order over USD 10, get USD 7 off",
                "code_mini_spend": "10",
                "code_promotionurl": "https://s.click.aliexpress.com/e/_x",
                "code_availabletime_start": "2030-01-01 00:00:00",
                "code_availabletime_end": "2030-12-31 23:59:59",
            },
        }
    )
    assert len(coupons) == 1
    assert coupons[0].code == "GMG20207"
    assert coupons[0].discount_type == CouponDiscountType.OTHER
    assert coupons[0].discount_value is None
    assert coupons[0].minimum_spend == Decimal("10")
    assert coupons[0].coupon_url == "https://s.click.aliexpress.com/e/_x"
    assert coupons[0].start_at is not None
    assert coupons[0].end_at is not None


def test_extracts_brl_discount_from_official_description():
    coupons = extract_aliexpress_coupons(
        {
            "promo_code_info": {
                "promo_code": "BRL7",
                "code_value": "On order over BRL 10, get BRL 7 off",
            }
        }
    )
    assert coupons[0].discount_type == CouponDiscountType.FIXED
    assert coupons[0].discount_value == Decimal("7")
    assert coupons[0].minimum_spend == Decimal("10")


def test_extracts_code():
    coupons = extract_aliexpress_coupons({"promo_code_info": {"promo_code": "PDF01"}})
    assert len(coupons) == 1
    assert coupons[0].code == "PDF01"


def test_extracts_fixed_discount():
    coupons = extract_aliexpress_coupons(
        {"coupon": {"coupon_code": "FIX10", "discount_value": "10", "minimum_spend": "50"}}
    )
    assert coupons[0].discount_type == CouponDiscountType.FIXED
    assert coupons[0].discount_value == Decimal("10")


def test_extracts_percentage():
    coupons = extract_aliexpress_coupons(
        {"coupon": {"code": "P15", "discount_percentage": "15"}}
    )
    assert coupons[0].discount_type == CouponDiscountType.PERCENTAGE
    assert coupons[0].discount_percentage == Decimal("15")


def test_extracts_minimum_spend():
    coupons = extract_aliexpress_coupons(
        {"coupon": {"code": "M", "discount_value": "5", "order_min_amount": "90"}}
    )
    assert coupons[0].minimum_spend == Decimal("90")


def test_extracts_maximum_discount():
    coupons = extract_aliexpress_coupons(
        {"coupon": {"code": "M", "discount_percentage": "10", "max_discount": "80"}}
    )
    assert coupons[0].maximum_discount == Decimal("80")


def test_extracts_validity():
    coupons = extract_aliexpress_coupons(
        {
            "coupon": {
                "code": "V",
                "start_time": "2030-01-10 00:00:00",
                "end_time": "2030-01-15 23:59:59",
            }
        }
    )
    assert coupons[0].start_at is not None
    assert coupons[0].end_at is not None


def test_extracts_url():
    coupons = extract_aliexpress_coupons(
        {"coupon": {"code": "U", "coupon_url": "https://example.com/c"}}
    )
    assert coupons[0].coupon_url == "https://example.com/c"


def test_extracts_from_nested_dict():
    item = {"product": {"promotions": {"coupon_info": {"coupon_code": "NEST1"}}}}
    coupons = extract_aliexpress_coupons(item)
    assert any(c.code == "NEST1" for c in coupons)


def test_extracts_list_of_coupons():
    item = {"coupons": [{"coupon_code": "L1"}, {"coupon_code": "L2"}]}
    coupons = extract_aliexpress_coupons(item)
    codes = {c.code for c in coupons}
    assert codes == {"L1", "L2"}


def test_extracts_valid_json_string():
    item = {"promo_code_info": '{"promo_code": "JS1", "discount_value": "5"}'}
    coupons = extract_aliexpress_coupons(item)
    assert any(c.code == "JS1" for c in coupons)


def test_ignores_invalid_json_string():
    item = {"promo_code_info": "{invalid json"}
    assert extract_aliexpress_coupons(item) == []


def test_no_coupon_returns_empty_list():
    item = {"product_id": "1", "product_title": "X", "sale_price": "10"}
    assert extract_aliexpress_coupons(item) == []


def test_generic_discount_alone_does_not_create_coupon():
    assert extract_aliexpress_coupons({"discount": "50%"}) == []


def test_removes_duplicate_coupons():
    item = {"coupons": [{"coupon_code": "D1"}, {"coupon_code": "D1"}]}
    coupons = extract_aliexpress_coupons(item)
    assert len(coupons) == 1


def test_preserves_raw_metadata():
    coupons = extract_aliexpress_coupons({"coupon": {"coupon_code": "R1"}})
    assert "raw_coupon" in coupons[0].metadata


def test_limits_depth():
    item = {"a": {"b": {"c": {"d": {"coupon_info": {"coupon_code": "DEEP"}}}}}}
    coupons = extract_aliexpress_coupons(item)
    assert all(c.code != "DEEP" for c in coupons)


def test_does_not_break_on_unexpected_structure():
    assert extract_aliexpress_coupons("not a dict") == []
    assert extract_aliexpress_coupons({"coupons": "weird"}) == []
    assert extract_aliexpress_coupons({"coupon": None}) == []
