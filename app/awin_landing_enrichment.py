import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import httpx

from app.awin_product_feed import (
    AwinFeedEnrichmentMetrics,
    collect_offer_url_candidates,
    extract_landing_url,
    extract_merchant_product_id_from_url,
    is_campaign_or_category_url,
    parse_feed_price,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

OG_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']og:image["\']',
    re.IGNORECASE,
)
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class LandingProductData:
    image_url: str | None
    price: Decimal | None
    old_price: Decimal | None
    currency: str | None
    product_name: str | None
    in_stock: bool | None


def resolve_product_landing_url(offer: dict[str, Any]) -> str | None:
    for candidate in collect_offer_url_candidates(offer):
        landing = extract_landing_url(candidate) or candidate
        if not landing:
            continue
        if is_campaign_or_category_url(landing):
            continue
        if extract_merchant_product_id_from_url(landing):
            return landing
    return None


def _first_http_url(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith("http") else None
    if isinstance(value, list):
        for item in value:
            found = _first_http_url(item)
            if found:
                return found
    return None


def _walk_json_ld(node: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        types = node.get("@type")
        type_names = (
            [types]
            if isinstance(types, str)
            else [item for item in types or [] if isinstance(item, str)]
        )
        if any(name.lower() == "product" for name in type_names):
            found.append(node)
        for value in node.values():
            found.extend(_walk_json_ld(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_json_ld(item))
    return found


def _parse_offer_node(offers: object) -> tuple[Decimal | None, Decimal | None, str | None, bool | None]:
    nodes = offers if isinstance(offers, list) else [offers]
    price: Decimal | None = None
    old_price: Decimal | None = None
    currency: str | None = None
    in_stock: bool | None = None

    for node in nodes:
        if not isinstance(node, dict):
            continue
        current = parse_feed_price(node.get("price") or node.get("lowPrice"))
        high = parse_feed_price(node.get("highPrice"))
        if current is not None and price is None:
            price = current
        if high is not None and old_price is None and (current is None or high > current):
            old_price = high
        currency_value = node.get("priceCurrency")
        if currency_value and currency is None:
            currency = str(currency_value).upper()
        availability = str(node.get("availability") or "").lower()
        if availability:
            in_stock = "instock" in availability.replace("_", "").replace(" ", "")
    return price, old_price, currency, in_stock


def parse_landing_html(html: str) -> LandingProductData:
    image_url = None
    og_match = OG_IMAGE_RE.search(html or "")
    if og_match:
        image_url = next((group for group in og_match.groups() if group), None)

    price = None
    old_price = None
    currency = None
    product_name = None
    in_stock = None

    for block in JSON_LD_RE.findall(html or ""):
        try:
            payload = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for product in _walk_json_ld(payload):
            if product_name is None and product.get("name"):
                product_name = str(product.get("name")).strip() or None
            json_image = _first_http_url(product.get("image"))
            if json_image:
                image_url = json_image
            offer_price, offer_old, offer_currency, offer_stock = _parse_offer_node(
                product.get("offers")
            )
            if offer_price is not None:
                price = offer_price
            if offer_old is not None:
                old_price = offer_old
            if offer_currency:
                currency = offer_currency
            if offer_stock is not None:
                in_stock = offer_stock
            if image_url and price is not None:
                break
        if image_url and price is not None:
            break

    return LandingProductData(
        image_url=image_url,
        price=price,
        old_price=old_price,
        currency=currency,
        product_name=product_name,
        in_stock=in_stock,
    )


def fetch_landing_product_data(
    landing_url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> LandingProductData | None:
    host = urlparse(landing_url).netloc.lower()
    if not host:
        return None

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(landing_url, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Landing fetch failed url=%s error=%s", host, exc)
        return None

    if response.status_code >= 400:
        logger.warning(
            "Landing fetch HTTP %s url=%s",
            response.status_code,
            host,
        )
        return None

    return parse_landing_html(response.text)


def enrich_offer_from_landing(
    offer: dict[str, Any],
    metrics: AwinFeedEnrichmentMetrics | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    stats = metrics or AwinFeedEnrichmentMetrics()
    enriched = dict(offer)
    if enriched.get("image_url") and enriched.get("price") is not None:
        return enriched

    landing_url = resolve_product_landing_url(offer)
    if not landing_url:
        return enriched

    product = fetch_landing_product_data(landing_url, timeout=timeout)
    if product is None:
        return enriched
    if product.in_stock is False:
        return enriched
    if product.currency and product.currency != "BRL":
        return enriched

    changed = False
    if not enriched.get("image_url") and product.image_url:
        enriched["image_url"] = product.image_url
        stats.offers_with_image += 1
        changed = True
    if enriched.get("price") is None and product.price is not None:
        enriched["price"] = float(product.price)
        stats.offers_with_current_price += 1
        changed = True
    if (
        enriched.get("old_price") is None
        and product.old_price is not None
        and product.price is not None
        and product.old_price > product.price
    ):
        enriched["old_price"] = float(product.old_price)
        stats.offers_with_old_price += 1
        changed = True

    if not changed:
        return enriched

    metadata = dict(enriched.get("metadata") or {})
    metadata["landing_enriched"] = True
    metadata["landing_url"] = landing_url
    if product.product_name:
        metadata["landing_product_name"] = product.product_name
    enriched["metadata"] = metadata
    enriched["currency"] = "BRL"
    stats.offers_enriched += 1
    return enriched


def enrich_offers_from_landing(
    offers: list[dict[str, Any]],
    metrics: AwinFeedEnrichmentMetrics | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    stats = metrics or AwinFeedEnrichmentMetrics()
    result: list[dict[str, Any]] = []
    for offer in offers:
        needs_image = not offer.get("image_url")
        needs_price = offer.get("price") is None
        if not needs_image and not needs_price:
            result.append(offer)
            continue
        if not resolve_product_landing_url(offer):
            result.append(offer)
            continue
        result.append(enrich_offer_from_landing(offer, stats, timeout=timeout))
    return result
