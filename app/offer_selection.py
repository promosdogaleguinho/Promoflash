from app.models import Promotion
from app.offer_grouper import group_by_product
from app.offer_ranker import select_best_offer
from app.product_identity import build_product_key


def _effective_price(promotion: Promotion) -> float:
    price = (
        promotion.final_price
        if promotion.final_price is not None
        else promotion.price
    )
    return price if price is not None else float("inf")


def _priority(promotion: Promotion) -> tuple[float, float, float]:
    return (
        promotion.promotion_score or 0.0,
        promotion.discount_percentage or 0.0,
        -_effective_price(promotion),
    )


def _best_price_rank(promotion: Promotion) -> tuple[float, float, float]:
    return (
        _effective_price(promotion),
        -(promotion.promotion_score or 0.0),
        -(promotion.discount_percentage or 0.0),
    )


def _parent_product_key(promotion: Promotion) -> str:
    parent_product_id = (promotion.metadata or {}).get("parent_product_id")
    if parent_product_id:
        return f"{promotion.source}:product:{parent_product_id}"
    return build_product_key(promotion)


def select_offer_candidates(promotions: list[Promotion]) -> list[Promotion]:
    sku_offers = [
        promotion
        for promotion in promotions
        if isinstance(
            (promotion.metadata or {}).get("sku_offer_group"), dict
        )
    ]
    regular_offers = [
        promotion
        for promotion in promotions
        if not isinstance(
            (promotion.metadata or {}).get("sku_offer_group"), dict
        )
    ]
    regular_groups = group_by_product(regular_offers)
    selected_regular = [
        select_best_offer(group) for group in regular_groups.values()
    ]

    sku_by_parent: dict[str, list[Promotion]] = {}
    for promotion in sku_offers:
        sku_by_parent.setdefault(_parent_product_key(promotion), []).append(
            promotion
        )
    selected_sku = [
        sorted(offers, key=_best_price_rank)[0]
        for offers in sku_by_parent.values()
        if offers
    ]
    return selected_regular + selected_sku


def select_diversified_offers(
    promotions: list[Promotion],
    max_total: int | None,
    max_per_parent: int,
) -> list[Promotion]:
    if max_per_parent <= 0:
        return []
    if max_total is not None and max_total <= 0:
        return []

    by_parent: dict[str, list[Promotion]] = {}
    for promotion in promotions:
        by_parent.setdefault(_parent_product_key(promotion), []).append(
            promotion
        )

    eligible_by_parent = {
        parent: sorted(offers, key=_best_price_rank)[:max_per_parent]
        for parent, offers in by_parent.items()
    }

    selected: list[Promotion] = []
    for index in range(max_per_parent):
        round_offers = [
            offers[index]
            for offers in eligible_by_parent.values()
            if index < len(offers)
        ]
        round_offers.sort(key=_priority, reverse=True)
        if max_total is None:
            selected.extend(round_offers)
            continue
        remaining = max_total - len(selected)
        selected.extend(round_offers[:remaining])
        if len(selected) >= max_total:
            break
    return selected
