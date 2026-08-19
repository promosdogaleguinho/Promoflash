import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.campaigns import get_campaign_display_name
from app.clients.aliexpress import AliExpressClient

MAX_CAMPAIGNS_TO_PRINT = 3
MAX_PRODUCTS_TO_PRINT = 3


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Erro: variável de ambiente {name} não configurada.", file=sys.stderr)
        sys.exit(1)
    return value


def _build_client() -> AliExpressClient:
    app_key = _require_env("ALIEXPRESS_APP_KEY")
    app_secret = _require_env("ALIEXPRESS_APP_SECRET")

    return AliExpressClient(
        app_key=app_key,
        app_secret=app_secret,
        endpoint=os.environ.get(
            "ALIEXPRESS_API_ENDPOINT", "https://api-sg.aliexpress.com/sync"
        ),
        sign_method=os.environ.get("ALIEXPRESS_SIGN_METHOD", "hmac"),
        tracking_id=os.environ.get("ALIEXPRESS_TRACKING_ID") or None,
        target_currency=os.environ.get("ALIEXPRESS_TARGET_CURRENCY", "BRL"),
        target_language=os.environ.get("ALIEXPRESS_TARGET_LANGUAGE", "PT"),
        ship_to_country=os.environ.get("ALIEXPRESS_SHIP_TO_COUNTRY", "BR"),
    )


def _print_campaign(campaign: dict) -> None:
    name = campaign.get("promotion_name") or ""
    print(f"\n  promotion_id: {campaign.get('promotion_id')}")
    print(f"  promotion_name: {name}")
    print(f"  campaign_display_name: {get_campaign_display_name(name)}")
    print(f"  start_time: {campaign.get('start_time')}")
    print(f"  end_time: {campaign.get('end_time')}")


def _print_product(index: int, product: dict) -> None:
    has_image = bool(
        product.get("product_main_image_url")
        or product.get("product_small_image_urls")
    )
    print(f"\n    [{index}]")
    print(f"      product_id: {product.get('product_id')}")
    print(f"      product_title: {product.get('product_title')}")
    print(f"      target_app_sale_price: {product.get('target_app_sale_price')}")
    print(f"      target_sale_price: {product.get('target_sale_price')}")
    print(
        f"      promotion_link: {'sim' if product.get('promotion_link') else 'não'}"
    )
    print(f"      image: {'sim' if has_image else 'não'}")


def main() -> None:
    client = _build_client()

    print("Buscando campanhas (featuredpromo.get)...")
    campaigns = client.featured_promo_get()
    print(f"campanhas encontradas={len(campaigns)}")

    for campaign in campaigns[:MAX_CAMPAIGNS_TO_PRINT]:
        _print_campaign(campaign)

        name = campaign.get("promotion_name") or ""
        display_name = get_campaign_display_name(name) or name
        products = client.featured_promo_products_get(
            promotion_name=campaign.get("promotion_name"),
            promotion_id=campaign.get("promotion_id"),
            page_no=1,
            page_size=MAX_PRODUCTS_TO_PRINT,
        )
        print(f"\n  campaign_name: {display_name}")
        print(f"  produtos encontrados={len(products)}")
        for index, product in enumerate(products[:MAX_PRODUCTS_TO_PRINT], start=1):
            _print_product(index, product)


if __name__ == "__main__":
    main()
