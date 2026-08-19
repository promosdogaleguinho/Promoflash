import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.clients.shopee_affiliate import (
    ShopeeAffiliateClient,
    ShopeeAffiliateError,
    build_product_offer_v2_query,
)


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]} (len={len(value)})"


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"ERRO: {name} não está definida neste terminal.", file=sys.stderr)
        print(
            "Defina no MESMO terminal antes de rodar, sem aspas no CMD:",
            file=sys.stderr,
        )
        print(f"  CMD:        set {name}=seu_valor", file=sys.stderr)
        print(f'  PowerShell: $env:{name}="seu_valor"', file=sys.stderr)
        sys.exit(1)
    if value.startswith('"') or value.startswith("'"):
        print(
            f"AVISO: {name} começa com aspas. No CMD, use set VAR=valor SEM aspas.",
            file=sys.stderr,
        )
    return value


def main() -> None:
    app_id = _require_env("SHOPEE_APP_ID")
    app_secret = _require_env("SHOPEE_APP_SECRET")
    api_url = os.environ.get(
        "SHOPEE_API_URL",
        "https://open-api.affiliate.shopee.com.br/graphql",
    ).strip()
    timeout = float(os.environ.get("SHOPEE_REQUEST_TIMEOUT", "30"))
    keyword = (sys.argv[1] if len(sys.argv) > 1 else "notebook").strip()

    print("=== Diagnóstico Shopee Affiliate ===")
    print(f"API URL:     {api_url}")
    print(f"APP_ID:      {_mask(app_id)}")
    print(f"APP_SECRET:  {_mask(app_secret)}")
    print(f"Timeout:     {timeout}s")
    print(f"Keyword:     {keyword}")
    print()

    client = ShopeeAffiliateClient(
        app_id=app_id,
        app_secret=app_secret,
        api_url=api_url,
        timeout=timeout,
        page_limit=5,
        max_retries=1,
    )

    query = build_product_offer_v2_query(keyword, page=1, limit=5)
    payload, headers = client._build_signed_request(query)
    auth = headers.get("Authorization", "")
    print(f"Authorization (prefixo): {auth[:48]}...")
    print(f"Payload bytes: {len(payload.encode('utf-8'))}")
    print()

    try:
        result = client.product_offer_v2(keyword=keyword, page=1, limit=5)
    except ShopeeAffiliateError as exc:
        print(f"FALHA na API: {type(exc).__name__}: {exc}")
        print()
        print("Se for auth/Invalid Authorization Header:")
        print("- confira APP_ID/SECRET no painel Affiliate Shopee BR")
        print("- no CMD NÃO use aspas: set SHOPEE_APP_ID=123456")
        print("- rode este script no MESMO terminal onde setou as variáveis")
        print("- o projeto NÃO lê arquivo .env automaticamente")
        sys.exit(2)

    nodes = result.get("nodes") or []
    page_info = result.get("pageInfo") or {}
    print(f"OK! nodes={len(nodes)} hasNextPage={page_info.get('hasNextPage')}")
    for index, node in enumerate(nodes[:3], start=1):
        print(
            f"  [{index}] shopId={node.get('shopId')} itemId={node.get('itemId')} "
            f"price={node.get('price')} offerLink={'sim' if node.get('offerLink') else 'não'}"
        )
        title = str(node.get("productName") or "")[:80]
        print(f"       {title}")

    if not nodes:
        print("API respondeu, mas sem produtos para essa keyword.")


if __name__ == "__main__":
    main()
