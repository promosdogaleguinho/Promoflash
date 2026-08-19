import csv
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.clients.awin_product_feed import open_feed_text_stream

logger = logging.getLogger(__name__)

PRODUCT_ID_PATH_RE = re.compile(
    r"/(?:produto|product)/(?P<product_id>\d+)",
    re.IGNORECASE,
)
PRODUCT_ID_QUERY_RE = re.compile(
    r"(?:^|[?&])(?:product[_-]?id|sku|id)=(?P<product_id>\d+)",
    re.IGNORECASE,
)
CAMPAIGN_PATH_HINTS = (
    "/promocao/",
    "/promoção/",
    "/ofertas/",
    "/perifericos/",
    "/periféricos/",
    "/hardware/",
    "/audio",
    "/áudio",
    "/busca?",
)

IMAGE_PRIORITY = (
    "large_image",
    "merchant_image_url",
    "aw_image_url",
    "image_url",
    "aw_thumb_url",
    "merchant_thumb_url",
    "thumb_url",
)

PRICE_PRIORITY = (
    "search_price",
    "display_price",
    "store_price",
    "sale_price",
    "price",
)

OLD_PRICE_KEYS = ("product_price_old", "rrp_price", "was_price", "original_price")


@dataclass(frozen=True)
class AwinFeedProduct:
    merchant_id: str
    merchant_product_id: str
    product_name: str | None
    search_price: Decimal | None
    display_price: Decimal | None
    old_price: Decimal | None
    currency: str | None
    image_url: str | None
    merchant_deep_link: str | None
    aw_deep_link: str | None
    in_stock: bool | None
    is_for_sale: bool | None
    raw: dict[str, str]


@dataclass
class AwinFeedEnrichmentMetrics:
    rows_parsed: int = 0
    products_indexed: int = 0
    offers_enriched: int = 0
    offers_without_match: int = 0
    offers_with_image: int = 0
    offers_with_current_price: int = 0
    offers_with_old_price: int = 0
    campaign_urls_skipped: int = 0
    download_failed: bool = False
    parsing_failed: bool = False


@dataclass
class ProductFeedIndex:
    by_merchant_product: dict[tuple[str, str], AwinFeedProduct] = field(
        default_factory=dict
    )
    by_product_id: dict[str, list[AwinFeedProduct]] = field(default_factory=dict)

    def add(self, product: AwinFeedProduct) -> None:
        key = (product.merchant_id, product.merchant_product_id)
        self.by_merchant_product[key] = product
        self.by_product_id.setdefault(product.merchant_product_id, []).append(product)

    def lookup(
        self,
        advertiser_id: str,
        product_id: str,
    ) -> AwinFeedProduct | None:
        direct = self.by_merchant_product.get((str(advertiser_id), str(product_id)))
        if direct is not None:
            return direct

        candidates = self.by_product_id.get(str(product_id)) or []
        same_merchant = [
            item for item in candidates if item.merchant_id == str(advertiser_id)
        ]
        if len(same_merchant) == 1:
            return same_merchant[0]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def __len__(self) -> int:
        return len(self.by_merchant_product)


def _normalize_header(value: str) -> str:
    return value.strip().lstrip("\ufeff").lower().replace(" ", "_")


def _cell(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def parse_feed_price(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    cleaned = text.replace("R$", "").replace(" ", "").strip()
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return amount


def _parse_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "sim"}:
        return True
    if text in {"0", "false", "no", "n", "nao", "não"}:
        return False
    return None


def choose_image_url(row: dict[str, str]) -> str | None:
    for key in IMAGE_PRIORITY:
        value = _cell(row, key)
        if value and value.lower().startswith(("http://", "https://")):
            return value
    return None


def choose_current_price(row: dict[str, str]) -> Decimal | None:
    for key in PRICE_PRIORITY:
        price = parse_feed_price(_cell(row, key))
        if price is not None:
            return price
    return None


def choose_old_price(
    row: dict[str, str],
    current_price: Decimal | None,
) -> Decimal | None:
    if current_price is None:
        return None
    for key in OLD_PRICE_KEYS:
        old_price = parse_feed_price(_cell(row, key))
        if old_price is not None and old_price > current_price:
            return old_price
    return None


def map_feed_row(row: dict[str, str]) -> AwinFeedProduct | None:
    merchant_id = _cell(row, "merchant_id", "advertiser_id")
    merchant_product_id = _cell(
        row,
        "merchant_product_id",
        "product_id",
        "aw_product_id",
    )
    deep_link = _cell(row, "merchant_deep_link", "deep_link", "aw_deep_link")
    if not merchant_product_id and deep_link:
        merchant_product_id = extract_merchant_product_id_from_url(deep_link)
    if not merchant_id or not merchant_product_id:
        return None

    current_price = choose_current_price(row)
    return AwinFeedProduct(
        merchant_id=str(merchant_id),
        merchant_product_id=str(merchant_product_id),
        product_name=_cell(row, "product_name", "product_title", "name"),
        search_price=parse_feed_price(_cell(row, "search_price")),
        display_price=parse_feed_price(
            _cell(row, "display_price", "store_price", "sale_price", "price")
        ),
        old_price=choose_old_price(row, current_price),
        currency=(_cell(row, "currency") or "").upper() or None,
        image_url=choose_image_url(row),
        merchant_deep_link=_cell(row, "merchant_deep_link", "deep_link"),
        aw_deep_link=_cell(row, "aw_deep_link"),
        in_stock=_parse_bool(_cell(row, "in_stock")),
        is_for_sale=_parse_bool(_cell(row, "is_for_sale")),
        raw=dict(row),
    )


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t|;")
        return dialect.delimiter
    except csv.Error:
        if sample.count("|") > sample.count(","):
            return "|"
        if sample.count(";") > sample.count(","):
            return ";"
        return ","


def parse_product_feed(
    content: bytes,
    metrics: AwinFeedEnrichmentMetrics | None = None,
) -> ProductFeedIndex:
    stats = metrics or AwinFeedEnrichmentMetrics()
    index = ProductFeedIndex()

    try:
        stream = open_feed_text_stream(content)
        sample = stream.read(8192)
        stream.seek(0)
        delimiter = _detect_delimiter(sample)
        reader = csv.DictReader(stream, delimiter=delimiter)
        if reader.fieldnames is None:
            stats.parsing_failed = True
            return index

        normalized_fields = [
            _normalize_header(name or "") for name in reader.fieldnames
        ]
        logger.info(
            "Awin product feed columns=%s delimiter=%r",
            normalized_fields[:30],
            delimiter,
        )
        for row in reader:
            stats.rows_parsed += 1
            normalized = {
                _normalize_header(str(key or "")): (
                    "" if value is None else str(value)
                )
                for key, value in row.items()
            }
            for field_name in normalized_fields:
                normalized.setdefault(field_name, "")

            product = map_feed_row(normalized)
            if product is None:
                continue
            index.add(product)
            stats.products_indexed += 1
    except Exception as exc:
        stats.parsing_failed = True
        logger.error("Awin product feed parsing failed: %s", exc)
        return ProductFeedIndex()

    logger.info(
        "Awin product feed rows parsed=%s products indexed=%s",
        stats.rows_parsed,
        stats.products_indexed,
    )
    return index


def extract_landing_url(url: str | None) -> str | None:
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None

    parsed = urlparse(text)
    query = parse_qs(parsed.query)
    for key in ("ued", "u", "url", "p", "dest", "clickref"):
        values = query.get(key) or []
        if values and values[0].strip():
            return unquote(values[0].strip())
    return text


def extract_merchant_product_id_from_url(url: str | None) -> str | None:
    landing = extract_landing_url(url)
    if not landing:
        return None
    match = PRODUCT_ID_PATH_RE.search(landing)
    if match:
        return match.group("product_id")
    query_match = PRODUCT_ID_QUERY_RE.search(landing)
    if query_match:
        return query_match.group("product_id")
    return None


def is_campaign_or_category_url(url: str | None) -> bool:
    landing = extract_landing_url(url)
    if not landing:
        return False
    if extract_merchant_product_id_from_url(landing):
        return False
    lowered = landing.lower()
    return any(hint in lowered for hint in CAMPAIGN_PATH_HINTS)


def collect_offer_url_candidates(offer: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in (
        "tracking_url",
        "affiliate_url",
        "url",
        "landing_url",
        "merchant_url",
    ):
        value = offer.get(key)
        if value:
            candidates.append(str(value))
    metadata = offer.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("raw_url", "landing_url", "merchant_url"):
            value = metadata.get(key)
            if value:
                candidates.append(str(value))
    # dedupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def resolve_offer_product_id(offer: dict[str, Any]) -> str | None:
    if offer.get("merchant_product_id"):
        return str(offer["merchant_product_id"])
    for url in collect_offer_url_candidates(offer):
        product_id = extract_merchant_product_id_from_url(url)
        if product_id:
            return product_id
    return None


def lookup_feed_product(
    index: ProductFeedIndex | dict[tuple[str, str], AwinFeedProduct],
    advertiser_id: str,
    *,
    tracking_url: str | None = None,
    merchant_product_id: str | None = None,
    offer: dict[str, Any] | None = None,
) -> AwinFeedProduct | None:
    product_id = merchant_product_id
    if not product_id and offer is not None:
        product_id = resolve_offer_product_id(offer)
    if not product_id and tracking_url:
        product_id = extract_merchant_product_id_from_url(tracking_url)
    if not product_id:
        return None

    if isinstance(index, ProductFeedIndex):
        return index.lookup(str(advertiser_id), str(product_id))
    return index.get((str(advertiser_id), str(product_id)))


def enrich_offer_dict(
    offer: dict[str, Any],
    index: ProductFeedIndex | dict[tuple[str, str], AwinFeedProduct],
    metrics: AwinFeedEnrichmentMetrics | None = None,
) -> dict[str, Any]:
    stats = metrics or AwinFeedEnrichmentMetrics()
    enriched = dict(offer)
    url_candidates = collect_offer_url_candidates(offer)
    primary_url = url_candidates[0] if url_candidates else None

    if primary_url and is_campaign_or_category_url(primary_url):
        # ainda tenta se algum candidato tiver /produto/id
        if not resolve_offer_product_id(offer):
            stats.campaign_urls_skipped += 1
            stats.offers_without_match += 1
            return enriched

    product = lookup_feed_product(
        index,
        str(offer.get("advertiser_id") or ""),
        tracking_url=primary_url,
        merchant_product_id=offer.get("merchant_product_id"),
        offer=offer,
    )
    if product is None:
        stats.offers_without_match += 1
        return enriched

    if product.in_stock is False or product.is_for_sale is False:
        stats.offers_without_match += 1
        return enriched

    currency = (product.currency or "BRL").upper()
    if currency and currency != "BRL":
        stats.offers_without_match += 1
        return enriched

    current_price = product.search_price or product.display_price
    old_price = product.old_price
    if old_price is not None and (
        current_price is None or old_price <= current_price
    ):
        old_price = None

    enriched["merchant_product_id"] = (
        enriched.get("merchant_product_id") or product.merchant_product_id
    )
    filled_price = False
    filled_old_price = False
    filled_image = False
    if current_price is not None and enriched.get("price") is None:
        enriched["price"] = float(current_price)
        stats.offers_with_current_price += 1
        filled_price = True
    if old_price is not None and enriched.get("old_price") is None:
        enriched["old_price"] = float(old_price)
        stats.offers_with_old_price += 1
        filled_old_price = True
    if product.image_url and not enriched.get("image_url"):
        enriched["image_url"] = product.image_url
        stats.offers_with_image += 1
        filled_image = True
    if enriched.get("currency") is None:
        enriched["currency"] = "BRL"

    metadata = dict(enriched.get("metadata") or {})
    if filled_price or filled_old_price or filled_image:
        metadata["feed_enriched"] = True
        metadata["merchant_product_id"] = product.merchant_product_id
        if product.product_name and not metadata.get("feed_product_name"):
            metadata["feed_product_name"] = product.product_name
        enriched["metadata"] = metadata
        stats.offers_enriched += 1
    else:
        # match sem preencher campo ausente (já tinha dados ou produto sem valor útil)
        if (
            enriched.get("price") is None
            and not enriched.get("image_url")
            and current_price is None
            and not product.image_url
        ):
            stats.offers_without_match += 1
        enriched["metadata"] = metadata
    return enriched


def enrich_offers_with_feed(
    offers: list[dict[str, Any]],
    index: ProductFeedIndex | dict[tuple[str, str], AwinFeedProduct],
    metrics: AwinFeedEnrichmentMetrics | None = None,
) -> list[dict[str, Any]]:
    stats = metrics or AwinFeedEnrichmentMetrics()
    return [enrich_offer_dict(offer, index, stats) for offer in offers]


def parse_google_money(value: object) -> tuple[Decimal | None, str | None]:
    """Parse preços no formato Google Shopping: '1999.90 BRL' ou 'R$ 1.999,90'."""
    if value is None:
        return None, None
    if isinstance(value, dict):
        amount = value.get("value") or value.get("amount") or value.get("price")
        currency = value.get("currency") or value.get("currency_code")
        price = parse_feed_price(amount)
        return price, str(currency).upper() if currency else None

    text = str(value).strip()
    if not text:
        return None, None

    currency = None
    parts = text.split()
    if len(parts) >= 2 and parts[-1].isalpha() and len(parts[-1]) == 3:
        currency = parts[-1].upper()
        text = " ".join(parts[:-1])
    return parse_feed_price(text), currency


def _nested_get(data: dict[str, Any], *paths: tuple[str, ...]) -> object:
    for path in paths:
        current: object = data
        ok = True
        for key in path:
            if not isinstance(current, dict) or key not in current:
                ok = False
                break
            current = current[key]
        if ok:
            return current
    return None


def map_enhanced_feed_product(
    row: dict[str, Any],
    default_merchant_id: str,
) -> AwinFeedProduct | None:
    """Mapeia uma linha JSONL do Enhanced Feed (Google Format)."""
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    basic = (
        row.get("product_basic")
        if isinstance(row.get("product_basic"), dict)
        else {}
    )
    price_section = (
        row.get("price_availability")
        if isinstance(row.get("price_availability"), dict)
        else {}
    )

    merchant_id = str(
        meta.get("advertiser_id")
        or row.get("advertiser_id")
        or default_merchant_id
    )
    product_id = (
        _nested_get(row, ("product_basic", "id"), ("id",))
        or basic.get("id")
        or row.get("id")
    )
    if product_id is None or str(product_id).strip() == "":
        return None

    title = (
        _nested_get(row, ("product_basic", "title"), ("title",))
        or basic.get("title")
        or row.get("title")
    )
    link = (
        _nested_get(row, ("product_basic", "link"), ("link",))
        or basic.get("link")
        or row.get("link")
        or row.get("mobile_link")
    )
    image = (
        _nested_get(row, ("product_basic", "image_link"), ("image_link",))
        or basic.get("image_link")
        or row.get("image_link")
        or row.get("additional_image_link")
    )
    if isinstance(image, list):
        image = image[0] if image else None

    sale_price, sale_currency = parse_google_money(
        price_section.get("sale_price")
        if price_section
        else row.get("sale_price")
    )
    list_price, list_currency = parse_google_money(
        price_section.get("price") if price_section else row.get("price")
    )
    current_price = sale_price or list_price
    old_price = None
    if sale_price is not None and list_price is not None and list_price > sale_price:
        old_price = list_price
    currency = sale_currency or list_currency or "BRL"

    availability = str(
        price_section.get("availability")
        if price_section
        else row.get("availability")
        or ""
    ).lower()
    in_stock = None
    if availability:
        in_stock = availability in {"in_stock", "instock", "available"}

    return AwinFeedProduct(
        merchant_id=merchant_id,
        merchant_product_id=str(product_id).strip(),
        product_name=str(title).strip() if title else None,
        search_price=current_price,
        display_price=current_price,
        old_price=old_price,
        currency=currency,
        image_url=str(image).strip() if image else None,
        merchant_deep_link=str(link).strip() if link else None,
        aw_deep_link=None,
        in_stock=in_stock,
        is_for_sale=True if in_stock is not False else False,
        raw={k: str(v) for k, v in row.items() if not isinstance(v, (dict, list))},
    )


def parse_enhanced_feed_jsonl(
    content: bytes,
    advertiser_id: str | int,
    metrics: AwinFeedEnrichmentMetrics | None = None,
) -> ProductFeedIndex:
    """Parseia JSONL do endpoint Get Enhanced Feed (Google Format)."""
    import json

    stats = metrics or AwinFeedEnrichmentMetrics()
    index = ProductFeedIndex()
    merchant_id = str(advertiser_id)

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception as exc:
        stats.parsing_failed = True
        logger.error("Awin enhanced feed decode failed: %s", exc)
        return index

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if "error" in payload and "product_basic" not in payload and "id" not in payload:
            logger.error(
                "Awin enhanced feed error line=%s payload=%s",
                line_number,
                payload,
            )
            continue

        stats.rows_parsed += 1
        product = map_enhanced_feed_product(payload, merchant_id)
        if product is None:
            continue
        index.add(product)
        stats.products_indexed += 1

    logger.info(
        "Awin enhanced feed parsed rows=%s indexed=%s advertiser=%s",
        stats.rows_parsed,
        stats.products_indexed,
        merchant_id,
    )
    return index
