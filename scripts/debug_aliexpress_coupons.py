"""Diagnóstico oficial de cupons/campanhas AliExpress (uso manual).

Consulta apenas:
- featuredpromo.get
- featuredpromo.products.get
- productdetail.get

Não inventa códigos. Não imprime secrets nem links completos.
Uso: python scripts/debug_aliexpress_coupons.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_coupon_extractor import extract_aliexpress_coupons
from app.models import Coupon

MAX_CAMPAIGNS = 3
MAX_PRODUCTS = 5


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Erro: variável de ambiente {name} não configurada.", file=sys.stderr)
        sys.exit(1)
    return value


def _build_client() -> AliExpressClient:
    return AliExpressClient(
        app_key=_require_env("ALIEXPRESS_APP_KEY"),
        app_secret=_require_env("ALIEXPRESS_APP_SECRET"),
        endpoint=os.environ.get(
            "ALIEXPRESS_API_ENDPOINT", "https://api-sg.aliexpress.com/sync"
        ),
        sign_method=os.environ.get("ALIEXPRESS_SIGN_METHOD", "hmac"),
        tracking_id=os.environ.get("ALIEXPRESS_TRACKING_ID") or None,
        target_currency=os.environ.get("ALIEXPRESS_TARGET_CURRENCY", "BRL"),
        target_language=os.environ.get("ALIEXPRESS_TARGET_LANGUAGE", "PT"),
        ship_to_country=os.environ.get("ALIEXPRESS_SHIP_TO_COUNTRY", "BR"),
        debug_responses=True,
    )


def _sanitize_code(code: str | None) -> str:
    if not code:
        return "(sem código)"
    if len(code) <= 4:
        return code[0] + "***"
    return f"{code[:3]}***{code[-2:]}"


def _print_coupon(index: int, coupon: Coupon) -> None:
    print(f"  cupom [{index}]")
    print(f"    código: {_sanitize_code(coupon.code)}")
    print(f"    tipo: {coupon.discount_type.value}")
    print(f"    valor: {coupon.discount_value}")
    print(f"    mínimo: {coupon.minimum_spend}")
    print(f"    validade: {coupon.start_at} -> {coupon.end_at}")
    print(f"    possui URL: {'sim' if (coupon.coupon_url or coupon.affiliate_url) else 'não'}")


def main() -> None:
    client = _build_client()

    print("1) featuredpromo.get")
    campaigns = client.featured_promo_get()
    print(f"   campanhas={len(campaigns)}")
    for index, campaign in enumerate(campaigns[:MAX_CAMPAIGNS], start=1):
        print(
            f"   [{index}] id={campaign.get('promotion_id')} "
            f"name={campaign.get('promotion_name')}"
        )

    total_coupons = 0
    for campaign in campaigns[:MAX_CAMPAIGNS]:
        name = campaign.get("promotion_name")
        print(f"\n2) featuredpromo.products.get name={name}")
        products = client.featured_promo_products_get(
            promotion_name=name,
            promotion_id=campaign.get("promotion_id"),
            page_size=MAX_PRODUCTS,
        )
        print(f"   produtos={len(products)}")
        with_promo = sum(1 for product in products if product.get("promo_code_info"))
        print(f"   com promo_code_info no product list={with_promo}")

        product_ids = [
            str(product.get("product_id"))
            for product in products
            if product.get("product_id")
        ][:MAX_PRODUCTS]
        if not product_ids:
            continue

        print(f"\n3) productdetail.get ids={','.join(product_ids)}")
        details = client.product_detail_get(product_ids)
        print(f"   detalhes={len(details)}")
        for detail in details:
            coupons = extract_aliexpress_coupons(detail)
            total_coupons += len(coupons)
            has_info = bool(detail.get("promo_code_info"))
            print(
                f"   product_id={detail.get('product_id')} "
                f"promo_code_info={'sim' if has_info else 'não'} "
                f"cupons_extraidos={len(coupons)}"
            )
            for coupon_index, coupon in enumerate(coupons, start=1):
                _print_coupon(coupon_index, coupon)

    print(f"\nTotal de cupons oficiais identificados: {total_coupons}")


if __name__ == "__main__":
    main()
