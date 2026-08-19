"""Pré-visualização de mensagens de cupons e campanhas com dados fictícios.

Não realiza chamadas a APIs nem envia mensagens ao Telegram.
Uso: python scripts/preview_coupon_messages.py
"""

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.coupon_formatter import format_coupon_campaign
from app.coupon_lifecycle import get_timezone
from app.formatter import format_promotion
from app.models import (
    Coupon,
    CouponCampaign,
    CouponDiscountType,
    CouponScopeType,
    FormattedMessage,
    Promotion,
)

TZ = get_timezone("America/Sao_Paulo")
NOW = datetime(2030, 1, 12, 12, 0, tzinfo=TZ)


def _print(title: str, message: FormattedMessage) -> None:
    print("=" * 60)
    print(title)
    print("-" * 60)
    print(message.text)
    for action in message.actions:
        print(f"[{action.text}]")
    print()


def _meli_percentage() -> CouponCampaign:
    return CouponCampaign(
        source="mercadolivre",
        campaign_id="meli-15",
        title="Cupom Mercado Livre",
        affiliate_url="https://exemplo/meli",
        coupons=[
            Coupon(
                source="mercadolivre",
                code="MELICUPOM",
                discount_type=CouponDiscountType.PERCENTAGE,
                discount_percentage=Decimal("15"),
                minimum_spend=Decimal("79"),
                maximum_discount=Decimal("80"),
            )
        ],
    )


def _shopee_fixed() -> CouponCampaign:
    return CouponCampaign(
        source="shopee",
        campaign_id="shopee-tech",
        title="Cupom Shopee Tecnologia",
        affiliate_url="https://exemplo/shopee",
        coupons=[
            Coupon(
                source="shopee",
                discount_type=CouponDiscountType.FIXED,
                discount_value=Decimal("100"),
                minimum_spend=Decimal("999"),
                requires_activation=True,
            )
        ],
    )


def _aliexpress_event() -> CouponCampaign:
    def _c(code: str, value: str, minimum: str) -> Coupon:
        return Coupon(
            source="aliexpress",
            code=code,
            discount_type=CouponDiscountType.FIXED,
            discount_value=Decimal(value),
            minimum_spend=Decimal(minimum),
        )

    return CouponCampaign(
        source="aliexpress",
        campaign_id="ae-event",
        title="Novo evento AliExpress",
        affiliate_url="https://exemplo/ae-event",
        coupons=[
            _c("PDF01", "12", "90"),
            _c("PDF02", "28", "200"),
            _c("PDF03", "38", "300"),
        ],
    )


def _future_campaign() -> CouponCampaign:
    return CouponCampaign(
        source="aliexpress",
        campaign_id="ae-future",
        title="Novo evento AliExpress",
        description="Prepare-se!",
        affiliate_url="https://exemplo/ae-future",
        start_at=datetime(2030, 1, 20, 0, 0, tzinfo=TZ),
        announcement_at=NOW - timedelta(hours=1),
        announce_before_start=True,
        coupons=[
            Coupon(source="aliexpress", code="PDF01", discount_type=CouponDiscountType.FIXED, discount_value=Decimal("12"), minimum_spend=Decimal("90")),
        ],
    )


def _aliexpress_product_with_coupon() -> Promotion:
    return Promotion(
        external_id="AE1",
        source="aliexpress",
        title="Controle Sem Fio GameSir T4 Nova Lite",
        url="https://exemplo/produto",
        affiliate_url="https://exemplo/produto-aff",
        store="AliExpress",
        price=84.0,
        final_price=84.0,
        coupons=[
            Coupon(
                source="aliexpress",
                code="PDF01",
                scope_type=CouponScopeType.PRODUCT,
                scope_value="AE1",
                app_only=True,
                requires_coins=True,
                coins_amount=442,
            )
        ],
    )


def _shopee_product_separate_links() -> Promotion:
    return Promotion(
        external_id="SP1",
        source="shopee",
        title="Grand Theft Auto VI — Pré-venda oficial",
        url="https://exemplo/produto-shopee",
        affiliate_url="https://exemplo/produto-shopee-aff",
        store="Shopee",
        price=367.41,
        final_price=367.41,
        coupons=[
            Coupon(
                source="shopee",
                title="Cupom de R$ 60",
                discount_type=CouponDiscountType.FIXED,
                discount_value=Decimal("60"),
                affiliate_url="https://exemplo/cupom-shopee",
            )
        ],
    )


def _product_with_expired_coupon() -> Promotion:
    return Promotion(
        external_id="AE2",
        source="aliexpress",
        title="Produto com cupom expirado",
        url="https://exemplo/produto-exp",
        affiliate_url="https://exemplo/produto-exp-aff",
        store="AliExpress",
        price=50.0,
        final_price=50.0,
        coupons=[
            Coupon(
                source="aliexpress",
                code="OLD",
                discount_type=CouponDiscountType.FIXED,
                discount_value=Decimal("10"),
                end_at=NOW - timedelta(days=2),
            )
        ],
    )


def main() -> None:
    _print("1. Cupom Mercado Livre (percentual)", format_coupon_campaign(_meli_percentage(), NOW))
    _print("2. Cupom Shopee (valor fixo)", format_coupon_campaign(_shopee_fixed(), NOW))
    _print("3. Evento AliExpress (múltiplos cupons)", format_coupon_campaign(_aliexpress_event(), NOW))
    _print("4. Produto AliExpress com cupom e moedas", format_promotion(_aliexpress_product_with_coupon(), NOW))
    _print("5. Produto Shopee com links separados", format_promotion(_shopee_product_separate_links(), NOW))
    _print("6. Campanha futura", format_coupon_campaign(_future_campaign(), NOW))
    _print("7. Produto com cupom expirado (ignorado)", format_promotion(_product_with_expired_coupon(), NOW))


if __name__ == "__main__":
    main()
