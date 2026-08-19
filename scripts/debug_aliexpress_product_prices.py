import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.collectors.aliexpress import (
    _FINAL_PRICE_FIELDS,
    _OLD_PRICE_FIELDS,
    _PRICE_METADATA_FIELDS,
    _pick_first_price,
    _resolve_old_price,
)
from app.clients.aliexpress import AliExpressClient

DEFAULT_KEYWORD = "fone bluetooth"
MAX_PRODUCTS_TO_PRINT = 5


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


def _print_product(product: dict) -> None:
    title = product.get("product_title") or "Sem título"
    print(f"\nProduto: {title}")
    print(f"product_id: {product.get('product_id')}")
    print(f"promotion_link: {'sim' if product.get('promotion_link') else 'não'}")

    print("\nCampos de preço:")
    for field in _PRICE_METADATA_FIELDS:
        print(f"{field}: {product.get(field)}")

    final_price, price_source = _pick_first_price(product, _FINAL_PRICE_FIELDS)
    old_price, old_price_source = _resolve_old_price(product, final_price)

    print("\nPreço escolhido:")
    print(f"final_price: {final_price}")
    print(f"source: {price_source}")
    print(f"old_price: {old_price}")
    print(f"source: {old_price_source}")


def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_KEYWORD
    client = _build_client()

    print(f"Consultando AliExpress: keyword='{keyword}' ...")
    products = client.product_query(keywords=keyword, page_no=1, page_size=MAX_PRODUCTS_TO_PRINT)

    print(f"Produtos encontrados: {len(products)}")
    for product in products[:MAX_PRODUCTS_TO_PRINT]:
        _print_product(product)


if __name__ == "__main__":
    main()
