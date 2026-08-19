from unittest.mock import MagicMock

from app.collectors.aliexpress_featured_promotions import (
    AliExpressFeaturedPromotionsCollector,
)


def _raw_product(product_id: str, **overrides) -> dict:
    base = {
        "product_id": product_id,
        "product_title": f"Produto {product_id}",
        "product_detail_url": f"https://aliexpress.com/item/{product_id}.html",
        "promotion_link": f"https://s.click.aliexpress.com/e/{product_id}",
        "product_main_image_url": f"https://img.aliexpress.com/{product_id}.jpg",
        "target_app_sale_price": "79.90",
        "target_original_price": "199.90",
        "discount": "50%",
    }
    base.update(overrides)
    return base


def _campaign(name: str, promotion_id: str = "c-1") -> dict:
    return {"promotion_id": promotion_id, "promotion_name": name, "raw": {}}


def _build_collector(
    campaigns: list[dict],
    products_by_call: list[list[dict]],
    **config,
) -> AliExpressFeaturedPromotionsCollector:
    client = MagicMock()
    client.featured_promo_get.return_value = campaigns
    client.featured_promo_products_get.side_effect = products_by_call
    source_config = {
        "max_campaigns_per_run": 3,
        "max_items_per_campaign": 10,
        "max_items_per_run": 20,
        "allowed_campaigns": [],
        "blocked_campaigns": [],
    }
    source_config.update(config)
    return AliExpressFeaturedPromotionsCollector(
        client=client, source_config=source_config
    )


def test_featured_product_becomes_official_campaign():
    collector = _build_collector([_campaign("Weekly Deals")], [[_raw_product("1")]])
    item = collector.collect()[0]
    assert item["is_official_campaign"] is True


def test_featured_product_receives_campaign_name():
    collector = _build_collector([_campaign("Weekly Deals")], [[_raw_product("1")]])
    item = collector.collect()[0]
    assert item["campaign_name"] == "Oferta da semana"


def test_featured_product_receives_official_tag():
    collector = _build_collector([_campaign("Weekly Deals")], [[_raw_product("1")]])
    item = collector.collect()[0]
    assert "Campanha oficial" in item["promotion_tags"]


def test_weekly_deals_becomes_oferta_da_semana():
    collector = _build_collector([_campaign("Weekly Deals")], [[_raw_product("1")]])
    item = collector.collect()[0]
    assert "Oferta da semana" in item["promotion_tags"]


def test_campaign_without_products_does_not_break():
    collector = _build_collector([_campaign("Weekly Deals")], [[]])
    assert collector.collect() == []


def test_failing_campaign_does_not_block_others():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign("Weekly Deals", "c-1"),
        _campaign("Best Seller", "c-2"),
    ]
    client.featured_promo_products_get.side_effect = [
        RuntimeError("boom"),
        [_raw_product("2")],
    ]
    collector = AliExpressFeaturedPromotionsCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 3,
            "max_items_per_campaign": 10,
            "max_items_per_run": 20,
        },
    )
    items = collector.collect()
    assert [item["external_id"] for item in items] == ["2"]


def test_respects_max_campaigns_per_run():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign("Weekly Deals", "c-1"),
        _campaign("Best Seller", "c-2"),
        _campaign("New Arrival", "c-3"),
    ]
    client.featured_promo_products_get.side_effect = [
        [_raw_product("1")],
        [_raw_product("2")],
    ]
    collector = AliExpressFeaturedPromotionsCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 2,
            "max_items_per_campaign": 10,
            "max_items_per_run": 20,
        },
    )
    collector.collect()
    assert client.featured_promo_products_get.call_count == 2


def test_respects_max_items_per_campaign():
    products = [_raw_product(str(i)) for i in range(10)]
    collector = _build_collector(
        [_campaign("Weekly Deals")], [products], max_items_per_campaign=2
    )
    collector.collect()
    _, kwargs = collector._client.featured_promo_products_get.call_args
    assert kwargs["page_size"] == 2


def test_respects_max_items_per_run():
    products = [_raw_product(str(i)) for i in range(10)]
    collector = _build_collector(
        [_campaign("Weekly Deals")], [products], max_items_per_run=3
    )
    assert len(collector.collect()) == 3


def test_allowed_campaigns_filters():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign("Weekly Deals", "c-1"),
        _campaign("Random Sale", "c-2"),
    ]
    client.featured_promo_products_get.side_effect = [[_raw_product("1")]]
    collector = AliExpressFeaturedPromotionsCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 3,
            "max_items_per_campaign": 10,
            "max_items_per_run": 20,
            "allowed_campaigns": ["Weekly Deals"],
        },
    )
    collector.collect()
    assert client.featured_promo_products_get.call_count == 1


def test_blocked_campaigns_filters():
    client = MagicMock()
    client.featured_promo_get.return_value = [_campaign("Weekly Deals", "c-1")]
    collector = AliExpressFeaturedPromotionsCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 3,
            "max_items_per_campaign": 10,
            "max_items_per_run": 20,
            "blocked_campaigns": ["Weekly Deals"],
        },
    )
    assert collector.collect() == []
    assert client.featured_promo_products_get.call_count == 0


def test_no_campaigns_returns_empty_list():
    collector = _build_collector([], [])
    assert collector.collect() == []


def test_tags_are_not_duplicated():
    collector = _build_collector([_campaign("Weekly Deals")], [[_raw_product("1")]])
    item = collector.collect()[0]
    assert item["promotion_tags"].count("Oferta da semana") == 1
