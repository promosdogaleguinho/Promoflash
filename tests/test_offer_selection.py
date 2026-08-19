from app.models import Promotion
from app.offer_selection import (
    select_diversified_offers,
    select_offer_candidates,
)


def _offer(
    external_id: str,
    parent_id: str,
    price: float,
    score: float,
    discount: float,
    is_sku: bool = True,
    source: str = "aliexpress",
) -> Promotion:
    metadata = {"parent_product_id": parent_id}
    if is_sku:
        metadata["sku_offer_group"] = {
            "product_id": parent_id,
            "material_signature": external_id,
            "sku_ids": [external_id],
            "variations": [{"sku_id": external_id, "price": str(price)}],
            "coupon_key": "no-coupon",
        }
    return Promotion(
        external_id=external_id,
        source=source,
        title=f"Oferta {external_id}",
        url=f"https://example.test/{external_id}",
        price=price,
        final_price=price,
        discount_percentage=discount,
        promotion_score=score,
        metadata=metadata,
    )


def test_sku_candidates_keep_only_cheapest_per_parent():
    offers = [
        _offer("connector-a", "p1", 50, 80, 40),
        _offer("connector-b", "p1", 60, 90, 50),
    ]
    selected = select_offer_candidates(offers)
    assert [offer.external_id for offer in selected] == ["connector-a"]


def test_limits_one_offer_per_parent_and_prefers_lowest_price():
    offers = [
        _offer("best-score", "p1", 100, 90, 20),
        _offer("best-discount", "p1", 80, 80, 50),
        _offer("cheapest", "p1", 40, 70, 60),
        _offer("other-product", "p2", 100, 60, 20),
    ]
    selected = select_diversified_offers(
        offers, max_total=10, max_per_parent=1
    )
    selected_ids = {offer.external_id for offer in selected}
    assert selected_ids == {"cheapest", "other-product"}


def test_single_parent_does_not_occupy_all_execution_slots():
    offers = [
        _offer(f"p1-{index}", "p1", 50 + index, 100 - index, 40)
        for index in range(5)
    ]
    offers.extend(
        [
            _offer("p2-1", "p2", 70, 60, 20),
            _offer("p3-1", "p3", 80, 50, 15),
        ]
    )
    selected = select_diversified_offers(
        offers, max_total=4, max_per_parent=1
    )
    parent_ids = [
        offer.metadata["parent_product_id"] for offer in selected
    ]
    assert parent_ids.count("p1") == 1
    assert "p2" in parent_ids
    assert "p3" in parent_ids
    assert next(
        offer.external_id for offer in selected if offer.metadata["parent_product_id"] == "p1"
    ) == "p1-0"


def test_lowest_price_wins_within_parent():
    offers = [
        _offer("expensive", "p1", 100, 80, 30),
        _offer("cheap", "p1", 90, 80, 30),
        _offer("cheapest", "p1", 70, 70, 50),
    ]
    selected = select_diversified_offers(
        offers, max_total=2, max_per_parent=1
    )
    assert [offer.external_id for offer in selected] == ["cheapest"]


def test_garmin_style_variants_keep_only_cheapest():
    offers = [
        _offer("glass-a", "1005001309780273", 14.79, 40, 6),
        _offer("glass-b", "1005001309780273", 14.69, 40, 6),
    ]
    candidates = select_offer_candidates(offers)
    selected = select_diversified_offers(
        candidates, max_total=None, max_per_parent=1
    )
    assert len(selected) == 1
    assert selected[0].external_id == "glass-b"
    assert selected[0].final_price == 14.69


def test_max_total_none_keeps_all_sources_without_global_cap():
    offers = [
        _offer(f"ae-{index}", f"ae-p{index}", 50, 90, 30, source="aliexpress")
        for index in range(8)
    ]
    offers.extend(
        [
            _offer(
                f"sh-{index}",
                f"sh-p{index}",
                40,
                40,
                10,
                is_sku=False,
                source="shopee",
            )
            for index in range(7)
        ]
    )
    selected = select_diversified_offers(
        offers, max_total=None, max_per_parent=1
    )
    assert len(selected) == 15
    assert sum(1 for offer in selected if offer.source == "aliexpress") == 8
    assert sum(1 for offer in selected if offer.source == "shopee") == 7


def test_max_total_zero_returns_empty():
    offers = [_offer("a", "p1", 50, 80, 20)]
    assert select_diversified_offers(offers, max_total=0, max_per_parent=1) == []
