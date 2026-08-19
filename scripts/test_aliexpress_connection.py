import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.aliexpress import (
    PRODUCT_QUERY_ROOT_KEY,
    AliExpressClient,
    _ensure_dict,
)

MAX_PRODUCTS_TO_PRINT = 3

DEFAULT_LANGUAGE = "PT"
DEFAULT_CURRENCY = "BRL"
DEFAULT_COUNTRY = "BR"

KEYWORDS = [
    "fone bluetooth",
    "smartwatch",
    "mouse gamer",
    "ssd",
    "controle bluetooth",
    "carregador usb c",
    "cabo usb c",
    "suporte celular",
    "teclado mecânico",
    "hub usb",
]

TEST_CASES = [
    {
        "keywords": keyword,
        "target_language": DEFAULT_LANGUAGE,
        "target_currency": DEFAULT_CURRENCY,
        "country": DEFAULT_COUNTRY,
    }
    for keyword in KEYWORDS
]


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


def _extract_resp_result(response: dict) -> dict:
    root = _ensure_dict(response.get(PRODUCT_QUERY_ROOT_KEY)) or response
    return _ensure_dict(root.get("resp_result"))


def _print_product(index: int, product: dict) -> None:
    print(f"\n[{index}]")
    print(f"  product_id: {product.get('product_id')}")
    print(f"  product_title: {product.get('product_title')}")
    print(f"  app_sale_price: {product.get('app_sale_price')}")
    print(f"  target_sale_price: {product.get('target_sale_price')}")
    print(f"  promotion_link: {'sim' if product.get('promotion_link') else 'não'}")
    print(f"  product_detail_url: {'sim' if product.get('product_detail_url') else 'não'}")


def _case_label(case: dict) -> str:
    return (
        f"{case['target_language']} / {case['target_currency']} / "
        f"{case['country']} / {case['keywords']}"
    )


def _run_case(client: AliExpressClient, case: dict) -> list[dict]:
    print(
        f"\nTestando keyword={case['keywords']}, language={case['target_language']}, "
        f"currency={case['target_currency']}, country={case['country']}"
    )

    raw_response = client.debug_product_query(
        keywords=case["keywords"],
        page_no=1,
        page_size=5,
        target_language=case["target_language"],
        target_currency=case["target_currency"],
        country=case["country"],
    )

    resp_result = _extract_resp_result(raw_response)
    products = client.product_query(
        keywords=case["keywords"],
        page_no=1,
        page_size=5,
        target_language=case["target_language"],
        target_currency=case["target_currency"],
        country=case["country"],
    )

    print(f"resp_code={resp_result.get('resp_code')}")
    print(f"resp_msg={resp_result.get('resp_msg')}")
    print(f"produtos encontrados={len(products)}")

    if products:
        print("Primeiros produtos:")
        for index, product in enumerate(products[:MAX_PRODUCTS_TO_PRINT], start=1):
            _print_product(index, product)

    return products


def _print_summary(results: list[tuple[str, int]]) -> None:
    print("\nResumo dos testes:\n")
    for label, count in results:
        print(f"{label}: {count} produtos")


def main() -> None:
    client = _build_client()

    results: list[tuple[str, int]] = []
    for case in TEST_CASES:
        products = _run_case(client, case)
        results.append((_case_label(case), len(products)))

    _print_summary(results)


if __name__ == "__main__":
    main()
