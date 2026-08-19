"""Probe Kabum product page meta tags for enrichment fallback."""

from __future__ import annotations

import json
import re
import sys

import httpx

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.kabum.com.br/produto/617572"
headers = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}
response = httpx.get(url, headers=headers, follow_redirects=True, timeout=30.0)
print("status", response.status_code, "len", len(response.text))
text = response.text

patterns = {
    "og_image_a": r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']',
    "og_image_b": r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']',
    "product_price": r'property=["\']product:price:amount["\'][^>]*content=["\']([^"\']+)["\']',
    "og_price": r'property=["\']og:price:amount["\'][^>]*content=["\']([^"\']+)["\']',
}
for name, pattern in patterns.items():
    match = re.search(pattern, text, flags=re.I)
    print(name, "=>", match.group(1) if match else None)

blocks = re.findall(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    text,
    flags=re.S | re.I,
)
print("jsonld_blocks", len(blocks))
for block in blocks[:5]:
    try:
        data = json.loads(block.strip())
    except json.JSONDecodeError as exc:
        print("jsonld_parse_error", exc)
        continue
    print("jsonld_type", type(data).__name__, str(data)[:400])
