import json
import unicodedata
from pathlib import Path

from app.models import Promotion
from app.promotion_quality import TAG_HIGH_INTENT, calculate_discount_percentage

RULES_FILENAME = "promotion_rules.json"

SCALAR_KEYS = (
    "min_promotion_score",
    "min_price",
    "max_price",
    "max_title_length",
    "soft_discount_percentage",
    "strong_discount_percentage",
    "relevance_min_sales",
    "relevance_min_rating",
)
BOOL_KEYS = (
    "require_relevance",
    "relevance_allow_official_store",
)
LIST_KEYS = (
    "blocked_keywords",
    "high_intent_keywords",
    "preferred_keywords",
    "trusted_brands",
)

_DEFAULT_RULES = {
    "min_promotion_score": 20,
    "min_price": 0,
    "max_price": 100000,
    "max_title_length": 300,
    "soft_discount_percentage": 10,
    "strong_discount_percentage": 20,
    "require_relevance": False,
    "relevance_allow_official_store": False,
    "relevance_min_sales": 100,
    "relevance_min_rating": 4.5,
    "blocked_keywords": [],
    "high_intent_keywords": [],
    "preferred_keywords": [],
    "trusted_brands": [],
}

_SOFT_DISCOUNT_BONUS = 8
_STRONG_DISCOUNT_BONUS = 15
_HIGH_INTENT_BONUS = 20
_PREFERRED_BONUS = 5
_TRUSTED_BRAND_BONUS = 15
_OFFICIAL_CAMPAIGN_BONUS = 25
_CAMPAIGN_NAME_BONUS = 15
_AFFILIATE_BONUS = 5

_COLLECTOR_TYPE_BONUS = {
    "featured_promotions": 25,
    "hot_products": 15,
}

_HIGH_SALES = 1000
_MEDIUM_SALES = 100
_LOW_SALES = 10


def load_promotion_rules(config_dir: str) -> dict:
    path = Path(config_dir) / RULES_FILENAME
    if not path.exists():
        return {"global": {}, "sources": {}, "categories": {}}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _normalize(text: str) -> str:
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _merge_layer(merged: dict, layer: dict) -> None:
    for key in SCALAR_KEYS:
        if key in layer and layer[key] is not None:
            merged[key] = layer[key]
    for key in BOOL_KEYS:
        if key in layer and layer[key] is not None:
            merged[key] = bool(layer[key])
    for key in LIST_KEYS:
        values = layer.get(key)
        if not values:
            continue
        existing = merged.get(key, [])
        merged[key] = existing + [item for item in values if item not in existing]


def _resolve_rules(rules: dict, source: str | None, category: str | None) -> dict:
    merged = {
        key: list(value) if isinstance(value, list) else value
        for key, value in _DEFAULT_RULES.items()
    }

    _merge_layer(merged, rules.get("global", {}))

    if source:
        source_rules = rules.get("sources", {}).get(source)
        if source_rules:
            _merge_layer(merged, source_rules)

    if category:
        category_rules = rules.get("categories", {}).get(category)
        if category_rules:
            _merge_layer(merged, category_rules)

    return merged


def _title_matches_any(title_norm: str, keywords: list[str]) -> bool:
    for keyword in keywords:
        if _normalize(keyword) in title_norm:
            return True
    return False


def _resolve_discount(promotion: Promotion) -> float:
    discount = promotion.discount_percentage
    if discount is None and promotion.old_price and promotion.final_price:
        discount = calculate_discount_percentage(
            promotion.final_price, promotion.old_price
        )
    return discount or 0.0


def _sales_bonus(sales: int | None) -> float:
    if not sales:
        return 0.0
    if sales >= _HIGH_SALES:
        return 15.0
    if sales >= _MEDIUM_SALES:
        return 8.0
    if sales >= _LOW_SALES:
        return 3.0
    return 0.0


def _compute_score(
    promotion: Promotion,
    discount: float,
    resolved: dict,
    has_high_intent: bool,
    has_preferred: bool,
    has_trusted_brand: bool,
) -> float:
    score = promotion.promotion_score or 0.0

    if discount >= resolved["soft_discount_percentage"]:
        score += _SOFT_DISCOUNT_BONUS
    if discount >= resolved["strong_discount_percentage"]:
        score += _STRONG_DISCOUNT_BONUS
    if has_high_intent:
        score += _HIGH_INTENT_BONUS
    if has_preferred:
        score += _PREFERRED_BONUS
    if has_trusted_brand:
        score += _TRUSTED_BRAND_BONUS
    if promotion.is_official_campaign:
        score += _OFFICIAL_CAMPAIGN_BONUS
    if promotion.campaign_name:
        score += _CAMPAIGN_NAME_BONUS

    score += _sales_bonus(promotion.sales)

    if promotion.affiliate_url:
        score += _AFFILIATE_BONUS

    collector_type = (promotion.metadata or {}).get("collector_type")
    score += _COLLECTOR_TYPE_BONUS.get(collector_type, 0)

    return score


def _add_tag(promotion: Promotion, tag: str) -> None:
    if tag not in promotion.promotion_tags:
        promotion.promotion_tags.append(tag)


def _check_mandatory(promotion: Promotion, resolved: dict) -> list[str]:
    reasons: list[str] = []

    if not promotion.title:
        reasons.append("sem titulo")
    if promotion.final_price is None:
        reasons.append("sem preco final")
    if not promotion.affiliate_url and not promotion.url:
        reasons.append("sem link")

    if reasons:
        return reasons

    title_norm = _normalize(promotion.title)
    for keyword in resolved["blocked_keywords"]:
        if _normalize(keyword) in title_norm:
            reasons.append(f"blocked keyword: {keyword}")
    if reasons:
        return reasons

    if promotion.final_price < resolved["min_price"]:
        reasons.append(f"preco abaixo do minimo ({resolved['min_price']})")
    if promotion.final_price > resolved["max_price"]:
        reasons.append(f"preco acima do maximo ({resolved['max_price']})")
    if len(promotion.title) > resolved["max_title_length"]:
        reasons.append("titulo muito longo")

    return reasons


def _has_social_proof(promotion: Promotion, resolved: dict) -> bool:
    min_sales = int(resolved.get("relevance_min_sales") or 0)
    min_rating = float(resolved.get("relevance_min_rating") or 0)
    if min_sales <= 0 or min_rating <= 0:
        return False
    if promotion.sales is None or promotion.rating is None:
        return False
    return promotion.sales >= min_sales and promotion.rating >= min_rating


def _is_relevant(
    promotion: Promotion,
    resolved: dict,
    has_high_intent: bool,
    has_trusted_brand: bool,
) -> bool:
    if not resolved.get("require_relevance"):
        return True
    if has_high_intent:
        return True
    if has_trusted_brand:
        return True
    if _has_social_proof(promotion, resolved):
        return True
    if resolved.get("relevance_allow_official_store") and promotion.is_official_store:
        return True
    return False


def apply_promotion_rules(promotion: Promotion, rules: dict) -> tuple[bool, list[str]]:
    resolved = _resolve_rules(rules, promotion.source, promotion.resolved_category)

    mandatory_reasons = _check_mandatory(promotion, resolved)
    if mandatory_reasons:
        return False, mandatory_reasons

    discount = _resolve_discount(promotion)
    if promotion.discount_percentage is None and discount:
        promotion.discount_percentage = discount

    title_norm = _normalize(promotion.title)
    has_high_intent = _title_matches_any(title_norm, resolved["high_intent_keywords"])
    has_preferred = _title_matches_any(title_norm, resolved["preferred_keywords"])
    has_trusted_brand = _title_matches_any(title_norm, resolved["trusted_brands"])

    if not _is_relevant(promotion, resolved, has_high_intent, has_trusted_brand):
        return False, ["produto irrelevante"]

    promotion.promotion_score = _compute_score(
        promotion,
        discount,
        resolved,
        has_high_intent,
        has_preferred,
        has_trusted_brand,
    )

    if has_high_intent:
        _add_tag(promotion, TAG_HIGH_INTENT)

    return True, []
