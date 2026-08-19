from datetime import datetime, timezone

from app.models import Promotion

MIN_DISCOUNT_PERCENTAGE = 20.0
MIN_ALIEXPRESS_DISCOUNT_PERCENTAGE = 10.0
MIN_PRICE_DIFF_PERCENTAGE = 10.0
MIN_SCORE_TO_APPROVE = 20.0
MIN_ALIEXPRESS_SALES_TO_APPROVE = 50
MIN_SALES_TO_HIGHLIGHT = 100
HIGH_SALES_THRESHOLD = 1000
MEDIUM_SALES_THRESHOLD = 100
LOW_SALES_THRESHOLD = 10

TAG_DISCOUNT = "Desconto"
TAG_OFFICIAL_CAMPAIGN = "Campanha oficial"
TAG_BEST_SELLER = "Mais vendido"
TAG_ALIEXPRESS = "Oferta AliExpress"
TAG_SHOPEE = "Oferta Shopee"
TAG_HIGH_INTENT = "Produto desejado"

SOURCE_ALIEXPRESS = "aliexpress"
SOURCE_SHOPEE = "shopee"


def calculate_discount_percentage(
    final_price: float | None, old_price: float | None
) -> float | None:
    if final_price is None or old_price is None:
        return None
    if old_price <= final_price:
        return None
    discount = (old_price - final_price) / old_price * 100
    return round(discount, 2)


def _sales_bonus(sales: int | None) -> float:
    if not sales:
        return 0.0
    if sales >= HIGH_SALES_THRESHOLD:
        return 15.0
    if sales >= MEDIUM_SALES_THRESHOLD:
        return 8.0
    if sales >= LOW_SALES_THRESHOLD:
        return 3.0
    return 0.0


def calculate_promotion_score(promotion: Promotion) -> float:
    score = 0.0

    if promotion.discount_percentage:
        score += promotion.discount_percentage

    if (
        promotion.old_price
        and promotion.final_price
        and promotion.old_price > promotion.final_price
    ):
        score += 10.0

    if promotion.is_official_campaign:
        score += 25.0

    if promotion.campaign_name:
        score += 15.0

    if promotion.affiliate_url:
        score += 5.0

    score += _sales_bonus(promotion.sales)

    metadata = promotion.metadata or {}
    if metadata.get("commission_rate"):
        score += 3.0

    shop_tier = metadata.get("shop_tier")
    if shop_tier == "mall":
        score += 8.0
    elif shop_tier == "star_plus":
        score += 5.0
    elif shop_tier == "star":
        score += 3.0

    if promotion.rating:
        score += min(float(promotion.rating), 5.0)

    return score


def _parse_iso_datetime(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _has_valid_identity(promotion: Promotion) -> bool:
    external_id = str(promotion.external_id or "").strip()
    if not external_id:
        return False
    if promotion.source == SOURCE_SHOPEE:
        return ":" in external_id
    return True


def _has_valid_period(promotion: Promotion, now: datetime | None = None) -> bool:
    metadata = promotion.metadata or {}
    current = now or datetime.now(timezone.utc)

    period_start = _parse_iso_datetime(metadata.get("period_start_at"))
    period_end = _parse_iso_datetime(metadata.get("period_end_at"))

    if period_start and period_start > current:
        return False
    if period_end and period_end < current:
        return False
    return True


def _has_real_price_drop(promotion: Promotion) -> bool:
    price = (
        promotion.final_price
        if promotion.final_price is not None
        else promotion.price
    )
    if (
        promotion.old_price is not None
        and price is not None
        and promotion.old_price > price
    ):
        return True
    if promotion.discount_percentage is not None and promotion.discount_percentage > 0:
        return True
    return False


def is_publishable_promotion(
    promotion: Promotion,
    now: datetime | None = None,
) -> bool:
    title = (promotion.title or "").strip()
    if not title:
        return False

    price = (
        promotion.final_price
        if promotion.final_price is not None
        else promotion.price
    )
    if price is None or price <= 0:
        return False

    if not promotion.affiliate_url:
        return False

    if not _has_valid_identity(promotion):
        return False

    if not _has_valid_period(promotion, now=now):
        return False

    # Exige sinal real de promoção (desconto > 0 ou preço antigo maior).
    # productOfferV2 da Shopee pode devolver produtos sem promoção ativa.
    if promotion.source in (SOURCE_ALIEXPRESS, SOURCE_SHOPEE):
        if not _has_real_price_drop(promotion):
            return False

    return True


def is_good_promotion(promotion: Promotion) -> bool:
    return is_publishable_promotion(promotion)


def _sanitize_prices(promotion: Promotion) -> None:
    price = (
        promotion.final_price
        if promotion.final_price is not None
        else promotion.price
    )
    if (
        promotion.old_price is not None
        and price is not None
        and promotion.old_price <= price
    ):
        promotion.old_price = None
    if promotion.discount_percentage is not None and promotion.discount_percentage <= 0:
        if promotion.old_price is None or price is None or promotion.old_price <= price:
            promotion.discount_percentage = None


def _build_promotion_tags(promotion: Promotion) -> list[str]:
    tags: list[str] = list(promotion.promotion_tags)

    def add(tag: str) -> None:
        if tag and tag not in tags:
            tags.append(tag)

    if promotion.discount_percentage and promotion.discount_percentage >= MIN_DISCOUNT_PERCENTAGE:
        add(TAG_DISCOUNT)

    if promotion.is_official_campaign:
        add(TAG_OFFICIAL_CAMPAIGN)

    if promotion.campaign_name:
        add(promotion.campaign_name)

    if promotion.sales and promotion.sales >= MIN_SALES_TO_HIGHLIGHT:
        add(TAG_BEST_SELLER)

    if promotion.source == SOURCE_ALIEXPRESS:
        add(TAG_ALIEXPRESS)

    if promotion.source == SOURCE_SHOPEE:
        add(TAG_SHOPEE)

    return tags


def apply_promotion_quality(promotion: Promotion) -> Promotion:
    _sanitize_prices(promotion)

    if promotion.discount_percentage is None:
        promotion.discount_percentage = calculate_discount_percentage(
            promotion.final_price, promotion.old_price
        )

    promotion.promotion_score = calculate_promotion_score(promotion)
    promotion.promotion_tags = _build_promotion_tags(promotion)
    return promotion
