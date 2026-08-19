from decimal import Decimal

from app.coupon_identity import build_coupon_key
from app.models import Coupon, CouponDiscountType, CouponScopeType, Promotion


def test_create_fixed_coupon():
    coupon = Coupon(
        source="aliexpress",
        code="PDF01",
        discount_type=CouponDiscountType.FIXED,
        discount_value=Decimal("12"),
        minimum_spend=Decimal("90"),
    )
    assert coupon.discount_type == CouponDiscountType.FIXED
    assert coupon.discount_value == Decimal("12")


def test_create_percentage_coupon():
    coupon = Coupon(
        source="mercadolivre",
        code="MELI15",
        discount_type=CouponDiscountType.PERCENTAGE,
        discount_percentage=Decimal("15"),
        maximum_discount=Decimal("80"),
    )
    assert coupon.discount_type == CouponDiscountType.PERCENTAGE
    assert coupon.discount_percentage == Decimal("15")


def test_coupon_without_code():
    coupon = Coupon(source="shopee", discount_value=Decimal("100"))
    assert coupon.code is None


def test_coupon_with_minimum_and_maximum():
    coupon = Coupon(
        source="shopee",
        minimum_spend=Decimal("999"),
        maximum_discount=Decimal("100"),
    )
    assert coupon.minimum_spend == Decimal("999")
    assert coupon.maximum_discount == Decimal("100")


def test_coupon_app_only_and_coins():
    coupon = Coupon(
        source="aliexpress",
        app_only=True,
        requires_coins=True,
        coins_amount=442,
    )
    assert coupon.app_only is True
    assert coupon.requires_coins is True
    assert coupon.coins_amount == 442


def test_coupon_key_is_stable():
    coupon = Coupon(source="aliexpress", code="PDF01")
    assert build_coupon_key(coupon) == build_coupon_key(coupon)


def test_material_change_alters_key():
    base = Coupon(source="aliexpress", code="PDF01", discount_value=Decimal("12"))
    changed = Coupon(source="aliexpress", code="PDF01", discount_value=Decimal("28"))
    assert build_coupon_key(base) != build_coupon_key(changed)


def test_spacing_and_case_do_not_change_key():
    a = Coupon(source="aliexpress", code="PDF01")
    b = Coupon(source="AliExpress", code="  pdf01 ")
    assert build_coupon_key(a) == build_coupon_key(b)


def test_scope_value_is_part_of_key():
    a = Coupon(source="s", code="X", scope_type=CouponScopeType.PRODUCT, scope_value="1")
    b = Coupon(source="s", code="X", scope_type=CouponScopeType.PRODUCT, scope_value="2")
    assert build_coupon_key(a) != build_coupon_key(b)


def test_legacy_promotion_fields_are_converted():
    promotion = Promotion(
        external_id="1",
        source="aliexpress",
        title="Produto",
        url="https://example.com",
        coupon_code="LEGACY10",
        coupon_description="Cupom legado",
    )
    assert len(promotion.coupons) == 1
    assert promotion.coupons[0].code == "LEGACY10"
    assert promotion.coupon_code == "LEGACY10"


def test_empty_coupons_list_does_not_break():
    promotion = Promotion(
        external_id="1",
        source="aliexpress",
        title="Produto",
        url="https://example.com",
    )
    assert promotion.coupons == []
