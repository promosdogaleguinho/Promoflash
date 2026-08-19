from app.models import Promotion


def _effective_price(promotion: Promotion) -> float | None:
    if promotion.final_price is not None:
        return promotion.final_price
    return promotion.price


def rank_offer(promotion: Promotion) -> float:
    price = _effective_price(promotion)
    if price is None:
        return float("-inf")

    score = (promotion.promotion_score or 0.0) * 50
    score += (promotion.discount_percentage or 0.0) * 20
    score -= price

    if promotion.is_official_store:
        score += 600
    if promotion.free_shipping:
        score += 400
    if promotion.rating is not None:
        score += promotion.rating * 5
    if promotion.sales is not None:
        score += min(promotion.sales / 100, 20)
    if promotion.coupon_code or promotion.coupons:
        score += 100

    return score


def select_best_offer(promotions: list[Promotion]) -> Promotion:
    return max(promotions, key=rank_offer)
