import re
import unicodedata
import hashlib
import json

from app.models import Promotion

_GENERIC_TERMS = [
    "promocao",
    "oferta",
    "original",
    "novo",
    "frete gratis",
    "envio imediato",
    "parcelado",
    "loja oficial",
]


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    lowercase = without_accents.lower()
    without_punctuation = re.sub(r"[^\w\s-]", " ", lowercase)
    compact_text = re.sub(r"\s+", " ", without_punctuation).strip()

    for term in sorted(_GENERIC_TERMS, key=len, reverse=True):
        compact_text = compact_text.replace(term, " ")

    words = compact_text.split()
    filtered_words = [word for word in words if word not in _GENERIC_TERMS]
    compact = " ".join(filtered_words)
    return re.sub(r"\s+", "-", compact.strip())


def build_offer_key(promotion: Promotion) -> str:
    group = (promotion.metadata or {}).get("sku_offer_group")
    if isinstance(group, dict):
        stable_commercial = {
            "product_id": group.get("product_id"),
            "material_signature": group.get("material_signature"),
            "sku_prices": sorted(
                (
                    str(variation.get("sku_id") or ""),
                    str(variation.get("price") or ""),
                )
                for variation in group.get("variations", [])
                if isinstance(variation, dict)
            ),
            "coupon_key": group.get("coupon_key") or "no-coupon",
        }
        encoded = json.dumps(
            stable_commercial,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"{promotion.source}:sku-offer:{digest}"
    return f"{promotion.source}:offer:{promotion.external_id}"


def build_product_key(promotion: Promotion) -> str:
    group = (promotion.metadata or {}).get("sku_offer_group")
    if isinstance(group, dict):
        parent_product_id = str(
            group.get("product_id")
            or (promotion.metadata or {}).get("parent_product_id")
            or promotion.canonical_product_id
            or promotion.external_id
        )
        product_key = f"{promotion.source}:product:{parent_product_id}"
        promotion.product_key = product_key
        return product_key

    if promotion.canonical_product_id:
        product_key = f"{promotion.source}:product:{promotion.canonical_product_id}"
    else:
        normalized_title = normalize_text(promotion.title)
        product_key = f"{promotion.source}:product-title:{normalized_title}"

    promotion.product_key = product_key
    return product_key


def build_product_price_key(promotion: Promotion) -> str:
    group = (promotion.metadata or {}).get("sku_offer_group")
    if isinstance(group, dict):
        return build_offer_key(promotion).replace(":sku-offer:", ":sku-price:")

    product_key = promotion.product_key or build_product_key(promotion)
    price = promotion.final_price if promotion.final_price is not None else promotion.price

    if price is None:
        price_part = "unknown-price"
    else:
        price_part = str(int(round(price * 100)))

    coupon_part = promotion.coupon_code or "no-coupon"
    payment_part = promotion.payment_method or "any-payment"

    return f"{promotion.source}:product-price:{product_key}:{price_part}:{coupon_part}:{payment_part}"
