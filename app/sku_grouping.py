import hashlib
import re
import unicodedata
from dataclasses import replace
from decimal import Decimal

from app.coupon_identity import build_coupon_key
from app.models import Promotion
from app.sku_models import SkuMetrics, SkuOfferGroup, SkuOfferVariation

DEFAULT_ABSOLUTE_TOLERANCE = Decimal("1.00")
DEFAULT_PERCENT_TOLERANCE = Decimal("0.02")


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def _coupon_signature(promotion: Promotion) -> str:
    if not promotion.coupons:
        return "no-coupon"
    return "|".join(sorted(build_coupon_key(coupon) for coupon in promotion.coupons))


def _within_price_tolerance(
    price: Decimal,
    minimum_price: Decimal,
    absolute_tolerance: Decimal,
    percent_tolerance: Decimal,
) -> bool:
    tolerance = max(absolute_tolerance, minimum_price * percent_tolerance)
    return price - minimum_price <= tolerance


def _cluster_by_price(
    promotions: list[Promotion],
    absolute_tolerance: Decimal,
    percent_tolerance: Decimal,
) -> list[list[Promotion]]:
    ordered = sorted(
        promotions,
        key=lambda promotion: Decimal(
            str((promotion.metadata["sku_variant"])["effective_price"])
        ),
    )
    if ordered and all(
        promotion.metadata["sku_variant"].get("grouping_dimension") == "length"
        for promotion in ordered
    ):
        return [ordered]

    clusters: list[list[Promotion]] = []
    for promotion in ordered:
        price = Decimal(str(promotion.metadata["sku_variant"]["effective_price"]))
        if not clusters:
            clusters.append([promotion])
            continue
        cluster_minimum = Decimal(
            str(clusters[-1][0].metadata["sku_variant"]["effective_price"])
        )
        if _within_price_tolerance(
            price, cluster_minimum, absolute_tolerance, percent_tolerance
        ):
            clusters[-1].append(promotion)
        else:
            clusters.append([promotion])
    return clusters


def _stable_group_id(
    product_id: str,
    material_signature: str,
    sku_ids: list[str],
    coupon_signature: str,
) -> str:
    identity = "|".join(
        [product_id, _normalize(material_signature), *sorted(sku_ids), coupon_signature]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{product_id}:sku-group:{digest}"


def _variation_from_promotion(promotion: Promotion) -> SkuOfferVariation:
    sku = promotion.metadata["sku_variant"]
    label = sku.get("cosmetic_label") or sku.get("variation_label") or "Padrão"
    return SkuOfferVariation(
        label=label,
        sku_id=str(sku["sku_id"]),
        price=Decimal(str(sku["effective_price"])),
        original_price=Decimal(str(sku["original_price"]))
        if sku.get("original_price") is not None
        else None,
        discount_rate=Decimal(str(sku["discount_rate"]))
        if sku.get("discount_rate") is not None
        else None,
        image_url=sku.get("image_url"),
        affiliate_url=sku.get("affiliate_url"),
        grouping_dimension=sku.get("grouping_dimension"),
    )


def _build_group(
    product_id: str,
    material_signature: str,
    promotions: list[Promotion],
    coupon_signature: str,
) -> SkuOfferGroup:
    variations = [_variation_from_promotion(promotion) for promotion in promotions]
    variations.sort(key=lambda variation: variation.price)
    prices = [variation.price for variation in variations]
    return SkuOfferGroup(
        product_id=product_id,
        material_signature=material_signature,
        sku_ids=sorted(variation.sku_id for variation in variations),
        variations=variations,
        display_price=min(prices),
        minimum_price=min(prices),
        maximum_price=max(prices),
        currency=str(
            promotions[0].metadata["sku_variant"].get("currency") or "BRL"
        ),
        coupon_key=coupon_signature,
    )


def _serialize_group(group: SkuOfferGroup) -> dict:
    return {
        "product_id": group.product_id,
        "material_signature": group.material_signature,
        "sku_ids": list(group.sku_ids),
        "variations": [
            {
                "label": variation.label,
                "sku_id": variation.sku_id,
                "price": str(variation.price),
                "original_price": str(variation.original_price)
                if variation.original_price is not None
                else None,
                "discount_rate": str(variation.discount_rate)
                if variation.discount_rate is not None
                else None,
                "image_url": variation.image_url,
                "affiliate_url": variation.affiliate_url,
                "grouping_dimension": variation.grouping_dimension,
                "shipping_fee": str(variation.shipping_fee)
                if variation.shipping_fee is not None
                else None,
                "delivery_days": variation.delivery_days,
                "min_delivery_days": variation.min_delivery_days,
                "max_delivery_days": variation.max_delivery_days,
                "ship_from_country": variation.ship_from_country,
            }
            for variation in group.variations
        ],
        "display_price": str(group.display_price),
        "minimum_price": str(group.minimum_price),
        "maximum_price": str(group.maximum_price),
        "currency": group.currency,
        "coupon_key": group.coupon_key,
        "shipping": group.shipping,
    }


def _group_title(
    title: str,
    material_signature: str,
    sibling_materials: set[str],
    public_variation_count: int,
) -> str:
    if public_variation_count <= 1:
        return title
    if material_signature == "__base__":
        return title
    if _normalize(material_signature) in _normalize(title):
        return title
    for sibling in sorted(sibling_materials, key=len, reverse=True):
        if sibling == "__base__" or sibling == material_signature:
            continue
        pattern = re.compile(re.escape(sibling), re.IGNORECASE)
        if pattern.search(title):
            return pattern.sub(material_signature, title, count=1)
    return f"{title} — {material_signature}"


def _promotion_from_group(
    group: SkuOfferGroup,
    source_promotions: list[Promotion],
    sibling_materials: set[str],
) -> Promotion:
    representative = min(
        source_promotions,
        key=lambda promotion: Decimal(
            str(promotion.metadata["sku_variant"]["effective_price"])
        ),
    )
    representative_variation = _variation_from_promotion(representative)
    group_id = _stable_group_id(
        group.product_id,
        group.material_signature,
        group.sku_ids,
        group.coupon_key,
    )
    metadata = dict(representative.metadata)
    metadata.pop("sku_variant", None)
    metadata["sku_offer_group"] = _serialize_group(group)
    metadata["parent_product_id"] = group.product_id
    public_variation_count = len(
        {
            _normalize(variation.label)
            for variation in group.variations
            if variation.label
        }
    )

    return replace(
        representative,
        external_id=group_id,
        canonical_product_id=group.product_id,
        title=_group_title(
            representative.title,
            group.material_signature,
            sibling_materials,
            public_variation_count,
        ),
        price=float(group.display_price),
        final_price=float(group.display_price),
        old_price=(
            float(representative_variation.original_price)
            if representative_variation.original_price is not None
            and representative_variation.original_price > group.display_price
            else None
        ),
        discount_percentage=float(representative_variation.discount_rate)
        if representative_variation.discount_rate is not None
        else None,
        affiliate_url=representative_variation.affiliate_url
        or representative.affiliate_url,
        image_url=representative_variation.image_url or representative.image_url,
        metadata=metadata,
    )


def group_sku_promotions(
    promotions: list[Promotion],
    absolute_tolerance: Decimal = DEFAULT_ABSOLUTE_TOLERANCE,
    percent_tolerance: Decimal = DEFAULT_PERCENT_TOLERANCE,
    metrics: SkuMetrics | None = None,
) -> list[Promotion]:
    passthrough = [
        promotion
        for promotion in promotions
        if "sku_variant" not in promotion.metadata
    ]
    sku_promotions = [
        promotion for promotion in promotions if "sku_variant" in promotion.metadata
    ]
    buckets: dict[tuple[str, str, str, str], list[Promotion]] = {}
    materials_by_product: dict[str, set[str]] = {}

    for promotion in sku_promotions:
        sku = promotion.metadata["sku_variant"]
        product_id = str(promotion.metadata["parent_product_id"])
        material = str(sku["material_signature"])
        currency = str(sku.get("currency") or "BRL")
        coupon_signature = _coupon_signature(promotion)
        buckets.setdefault(
            (product_id, material, currency, coupon_signature), []
        ).append(promotion)
        materials_by_product.setdefault(product_id, set()).add(material)

    grouped_promotions: list[Promotion] = []
    price_split_count = 0
    for (product_id, material, _, coupon_signature), bucket in buckets.items():
        unique_by_sku_id: dict[str, Promotion] = {}
        for promotion in bucket:
            sku_id = str(promotion.metadata["sku_variant"]["sku_id"])
            unique_by_sku_id.setdefault(sku_id, promotion)
        clusters = _cluster_by_price(
            list(unique_by_sku_id.values()),
            absolute_tolerance,
            percent_tolerance,
        )
        price_split_count += max(0, len(clusters) - 1)
        for cluster in clusters:
            group = _build_group(
                product_id, material, cluster, coupon_signature
            )
            grouped_promotions.append(
                _promotion_from_group(
                    group,
                    cluster,
                    materials_by_product.get(product_id, set()),
                )
            )
            if metrics is not None:
                metrics.groups_created += 1
                if len(group.sku_ids) > 1:
                    metrics.groups_with_multiple_skus += 1

    if metrics is not None:
        metrics.skus_split_by_price += price_split_count
        metrics.skus_split_by_material += sum(
            max(0, len(materials) - 1) for materials in materials_by_product.values()
        )
        metrics.final_sku_offers += len(grouped_promotions)
    return passthrough + grouped_promotions


def explode_sku_group_promotion(promotion: Promotion) -> list[Promotion]:
    group = (promotion.metadata or {}).get("sku_offer_group")
    if not isinstance(group, dict):
        return [promotion]

    product_id = str(group.get("product_id") or promotion.external_id)
    material_signature = str(group.get("material_signature") or "__base__")
    exploded: list[Promotion] = []
    for variation in group.get("variations", []):
        if not isinstance(variation, dict) or variation.get("price") is None:
            continue
        metadata = dict(promotion.metadata)
        metadata.pop("sku_offer_group", None)
        metadata["parent_product_id"] = product_id
        metadata["sku_variant"] = {
            "sku_id": str(variation.get("sku_id") or ""),
            "variation_label": str(variation.get("label") or "Padrão"),
            "material_signature": material_signature,
            "cosmetic_label": str(variation.get("label") or "Padrão"),
            "grouping_dimension": variation.get("grouping_dimension"),
            "effective_price": str(variation["price"]),
            "original_price": variation.get("original_price"),
            "discount_rate": variation.get("discount_rate"),
            "currency": group.get("currency") or "BRL",
            "image_url": variation.get("image_url"),
            "affiliate_url": variation.get("affiliate_url"),
            "availability_status": "unknown",
            "sku_status": "resolved",
        }
        price = Decimal(str(variation["price"]))
        original_price = (
            Decimal(str(variation["original_price"]))
            if variation.get("original_price") is not None
            else None
        )
        discount_rate = (
            Decimal(str(variation["discount_rate"]))
            if variation.get("discount_rate") is not None
            else None
        )
        exploded.append(
            replace(
                promotion,
                external_id=product_id,
                canonical_product_id=None,
                price=float(price),
                final_price=float(price),
                old_price=float(original_price)
                if original_price is not None and original_price > price
                else None,
                discount_percentage=float(discount_rate)
                if discount_rate is not None
                else None,
                affiliate_url=variation.get("affiliate_url")
                or promotion.affiliate_url,
                image_url=variation.get("image_url") or promotion.image_url,
                product_key=None,
                promotion_score=None,
                metadata=metadata,
            )
        )
    return exploded
