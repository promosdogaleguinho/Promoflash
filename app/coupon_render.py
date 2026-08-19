from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.coupon_lifecycle import is_coupon_active, is_coupon_expired
from app.models import Coupon, CouponDiscountType

MAX_PRODUCT_COUPONS = 2
MAX_CONDITION_TEXT_LENGTH = 80


def format_amount(value: Decimal | None) -> str:
    if value is None:
        return ""
    try:
        if value == value.to_integral_value():
            return str(int(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return f"{value:.2f}".replace(".", ",")


def _minimum_spend_suffix(coupon: Coupon) -> str:
    if coupon.minimum_spend is None:
        return ""
    return f" em compras a partir de R$ {format_amount(coupon.minimum_spend)}"


def build_benefit_line(coupon: Coupon) -> str | None:
    if (
        coupon.discount_type == CouponDiscountType.FIXED
        and coupon.discount_value is not None
    ):
        return f"R$ {format_amount(coupon.discount_value)} OFF{_minimum_spend_suffix(coupon)}"

    if (
        coupon.discount_type == CouponDiscountType.PERCENTAGE
        and coupon.discount_percentage is not None
    ):
        return (
            f"{format_amount(coupon.discount_percentage)}% OFF"
            f"{_minimum_spend_suffix(coupon)}"
        )

    if coupon.discount_type == CouponDiscountType.FREE_SHIPPING:
        return f"Frete grátis{_minimum_spend_suffix(coupon)}"

    if coupon.description:
        return coupon.description.strip()

    return None


def build_limit_line(coupon: Coupon) -> str | None:
    if coupon.maximum_discount is None:
        return None
    if coupon.discount_type != CouponDiscountType.PERCENTAGE:
        return None
    return f"Limite de R$ {format_amount(coupon.maximum_discount)} de desconto"


def build_condition_lines(coupon: Coupon) -> list[str]:
    lines: list[str] = []

    if coupon.app_only:
        lines.append("📱 Exclusivo no app")

    if coupon.requires_activation or coupon.requires_coupon_rescue:
        lines.append("🎟️ Requer ativação ou resgate")

    if coupon.requires_coins and coupon.coins_amount:
        lines.append(f"🪙 Use também {coupon.coins_amount} moedas no app")

    if coupon.payment_method:
        lines.append(f"💳 Válido para pagamento via {coupon.payment_method}")

    for condition in coupon.conditions:
        text = (condition or "").strip()
        if text:
            lines.append(text[:MAX_CONDITION_TEXT_LENGTH])

    return lines


def build_product_coupon_lines(coupon: Coupon) -> list[str]:
    header = f"🎟️ Cupom: {coupon.code}" if coupon.code else "🎟️ Cupom disponível"
    lines = [header]

    benefit = build_benefit_line(coupon)
    if benefit:
        lines.append(benefit)

    limit = build_limit_line(coupon)
    if limit:
        lines.append(limit)

    lines.extend(build_condition_lines(coupon))
    return lines


def build_campaign_coupon_lines(coupon: Coupon) -> list[str]:
    benefit = build_benefit_line(coupon)
    header = f"🎟️ {benefit}" if benefit else "🎟️ Cupom disponível"
    lines = [header]

    if coupon.code:
        lines.append(f"Código: {coupon.code}")

    limit = build_limit_line(coupon)
    if limit:
        lines.append(limit)

    lines.extend(build_condition_lines(coupon))
    return lines


def _benefit_magnitude(coupon: Coupon) -> Decimal:
    if coupon.discount_value is not None:
        return coupon.discount_value
    if coupon.maximum_discount is not None:
        return coupon.maximum_discount
    if coupon.discount_percentage is not None:
        return coupon.discount_percentage
    return Decimal(0)


def _end_at_sort_key(coupon: Coupon) -> float:
    if coupon.end_at is None:
        return float("inf")
    return coupon.end_at.timestamp()


def _priority_sort_key(coupon: Coupon) -> tuple:
    is_product = 1 if coupon.scope_type.value == "product" else 0
    is_campaign = 1 if coupon.scope_type.value == "campaign" else 0
    has_code = 1 if coupon.code else 0
    has_link = 1 if (coupon.affiliate_url or coupon.coupon_url) else 0
    return (
        -is_product,
        -float(_benefit_magnitude(coupon)),
        -is_campaign,
        _end_at_sort_key(coupon),
        -has_code,
        -has_link,
    )


def select_display_coupons(
    coupons: list[Coupon],
    now: datetime,
    max_coupons: int = MAX_PRODUCT_COUPONS,
) -> tuple[list[Coupon], bool]:
    usable = [coupon for coupon in coupons if not is_coupon_expired(coupon, now)]
    ordered = sorted(usable, key=_priority_sort_key)
    displayed = ordered[:max_coupons]
    has_more = len(ordered) > len(displayed)
    return displayed, has_more


def has_active_coupon(coupons: list[Coupon], now: datetime) -> bool:
    return any(is_coupon_active(coupon, now) for coupon in coupons)
