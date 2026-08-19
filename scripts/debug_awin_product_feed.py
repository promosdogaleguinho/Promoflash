"""Diagnóstico do Product Feed Awin (sem enviar Telegram).

Uso Create-a-Feed CSV:
  $env:AWIN_PRODUCT_FEED_URL="https://productdata.awin.com/..."
  python scripts/debug_awin_product_feed.py

Uso Enhanced Feed API (docs oficiais):
  $env:AWIN_OAUTH2_TOKEN="..."
  $env:AWIN_PUBLISHER_ID="..."
  python scripts/probe_awin_enhanced_feed.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.awin_product_feed import (
    extract_merchant_product_id_from_url,
    parse_product_feed,
)
from app.clients.awin_product_feed import (
    AwinProductFeedClient,
    sanitize_feed_url_for_log,
)


def main() -> None:
    feed_url = (os.environ.get("AWIN_PRODUCT_FEED_URL") or "").strip()
    if not feed_url:
        print("Erro: defina AWIN_PRODUCT_FEED_URL")
        print("Para Enhanced Feed OAuth, use scripts/probe_awin_enhanced_feed.py")
        sys.exit(1)

    print(f"Baixando feed: {sanitize_feed_url_for_log(feed_url)}")
    content = AwinProductFeedClient(feed_url).download()
    index = parse_product_feed(content)
    print(f"Produtos indexados: {len(index)}")

    sample_keys = list(index.by_merchant_product.keys())[:5]
    for key in sample_keys:
        product = index.by_merchant_product[key]
        print(
            f"- merchant={product.merchant_id} id={product.merchant_product_id} "
            f"price={product.search_price or product.display_price} "
            f"image={'yes' if product.image_url else 'no'} "
            f"name={(product.product_name or '')[:50]}"
        )

    test_url = (
        os.environ.get("AWIN_TEST_PRODUCT_URL")
        or "https://www.kabum.com.br/produto/134179/teste"
    )
    product_id = extract_merchant_product_id_from_url(test_url)
    print(f"\nTeste de match URL={test_url}")
    print(f"product_id extraído={product_id}")
    if product_id:
        for merchant_id in {key[0] for key in sample_keys} or {"17729"}:
            hit = index.lookup(merchant_id, product_id)
            print(f"lookup({merchant_id}, {product_id}) => {hit is not None}")


if __name__ == "__main__":
    main()
