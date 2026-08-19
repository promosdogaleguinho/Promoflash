from unittest.mock import MagicMock

from app.collectors.aliexpress import AliExpressCollector


def _raw_product(product_id: str, **overrides) -> dict:
    base = {
        "product_id": product_id,
        "product_title": f"Produto {product_id}",
        "product_detail_url": f"https://aliexpress.com/item/{product_id}.html",
        "promotion_link": f"https://s.click.aliexpress.com/e/{product_id}",
        "product_main_image_url": f"https://img.aliexpress.com/{product_id}.jpg",
        "target_app_sale_price": "79.90",
        "target_sale_price": "89.90",
        "app_sale_price": "99.90",
        "sale_price": "109.90",
        "target_original_price": "199.90",
        "original_price": "189.90",
        "discount": "50%",
        "commission_rate": "8.5%",
        "hot_product_commission_rate": "12%",
        "evaluate_rate": "92.5%",
        "lastest_volume": "1500",
        "first_level_category_name": "Electronics",
        "second_level_category_name": "Headphones",
        "shop_id": "shop-777",
        "shop_url": "https://aliexpress.com/store/777",
    }
    base.update(overrides)
    return base


def _build_collector(products: list[dict], max_items: int = 20) -> AliExpressCollector:
    client = MagicMock()
    client.product_query.return_value = products
    source_config = {"keywords": ["fone bluetooth"], "max_items_per_run": max_items}
    return AliExpressCollector(client=client, source_config=source_config)


def test_transforms_raw_item_into_expected_dict():
    collector = _build_collector([_raw_product("1")])
    items = collector.collect()

    assert len(items) == 1
    item = items[0]
    assert item["external_id"] == "1"
    assert item["source"] == "aliexpress"
    assert item["title"] == "Produto 1"
    assert item["url"] == "https://aliexpress.com/item/1.html"
    assert item["store"] == "AliExpress"
    assert item["image_url"] == "https://img.aliexpress.com/1.jpg"
    assert item["category"] == "Electronics"
    assert item["tags"] == ["Headphones"]
    assert item["seller_id"] == "shop-777"


def test_uses_promotion_link_as_affiliate_url():
    promo = "https://s.click.aliexpress.com/e/custom"
    collector = _build_collector([_raw_product("1", promotion_link=promo)])
    item = collector.collect()[0]

    assert item["affiliate_url"] == promo
    assert item["url"] == "https://aliexpress.com/item/1.html"


def test_final_price_prioritizes_target_app_sale_price():
    collector = _build_collector([_raw_product("1")])
    item = collector.collect()[0]

    assert item["final_price"] == 79.90
    assert item["price"] == 79.90
    assert item["metadata"]["price_source"] == "target_app_sale_price"


def test_final_price_uses_target_sale_price_when_target_app_missing():
    collector = _build_collector([_raw_product("1", target_app_sale_price="")])
    item = collector.collect()[0]

    assert item["final_price"] == 89.90
    assert item["metadata"]["price_source"] == "target_sale_price"


def test_final_price_falls_back_to_app_sale_price():
    collector = _build_collector(
        [_raw_product("1", target_app_sale_price="", target_sale_price="")]
    )
    item = collector.collect()[0]

    assert item["final_price"] == 99.90
    assert item["metadata"]["price_source"] == "app_sale_price"


def test_metadata_price_fields_and_source_are_filled():
    collector = _build_collector([_raw_product("1")])
    item = collector.collect()[0]

    price_fields = item["metadata"]["price_fields"]
    assert price_fields["target_app_sale_price"] == "79.90"
    assert price_fields["target_sale_price"] == "89.90"
    assert price_fields["discount"] == "50%"
    assert item["metadata"]["price_source"] == "target_app_sale_price"
    assert item["metadata"]["old_price_source"] == "target_original_price"


def test_old_price_prioritizes_target_original_price():
    collector = _build_collector([_raw_product("1")])
    item = collector.collect()[0]

    assert item["old_price"] == 199.90


def test_old_price_ignored_when_not_greater_than_final():
    collector = _build_collector(
        [_raw_product("1", target_original_price="70.00", original_price="60.00")]
    )
    item = collector.collect()[0]

    assert item["old_price"] is None


def test_removes_duplicates_by_product_id():
    products = [_raw_product("1"), _raw_product("1"), _raw_product("2")]
    collector = _build_collector(products)
    items = collector.collect()

    external_ids = [item["external_id"] for item in items]
    assert external_ids == ["1", "2"]


def test_respects_max_items_per_run():
    products = [_raw_product(str(i)) for i in range(10)]
    collector = _build_collector(products, max_items=3)
    items = collector.collect()

    assert len(items) == 3


def test_distributes_quota_across_keywords():
    client = MagicMock()

    def product_query(*, keywords, page_no, page_size):
        prefix = "fone" if keywords == "fone bluetooth" else "ctrl"
        return [_raw_product(f"{prefix}-{i}") for i in range(page_size + 2)]

    client.product_query.side_effect = product_query
    collector = AliExpressCollector(
        client=client,
        source_config={
            "keywords": ["fone bluetooth", "controle bluetooth"],
            "max_items_per_run": 4,
        },
    )
    items = collector.collect()

    assert len(items) == 4
    assert {item["metadata"]["keyword"] for item in items} == {
        "fone bluetooth",
        "controle bluetooth",
    }
    assert sum(1 for item in items if item["metadata"]["keyword"] == "fone bluetooth") == 2
    assert (
        sum(1 for item in items if item["metadata"]["keyword"] == "controle bluetooth")
        == 2
    )


def test_converts_price_string_to_float():
    collector = _build_collector([_raw_product("1", target_app_sale_price="1.234,56")])
    item = collector.collect()[0]

    assert isinstance(item["final_price"], float)
    assert item["final_price"] == 1234.56


def test_converts_discount_percentage():
    collector = _build_collector([_raw_product("1", discount="50%")])
    item = collector.collect()[0]

    assert item["discount_percentage"] == 50.0


def test_converts_volume_to_int():
    collector = _build_collector([_raw_product("1", lastest_volume="1500")])
    item = collector.collect()[0]

    assert item["sales"] == 1500


def test_preserves_raw_item_in_metadata():
    raw = _raw_product("1")
    collector = _build_collector([raw])
    item = collector.collect()[0]

    assert item["metadata"]["raw"] == raw
    assert item["metadata"]["keyword"] == "fone bluetooth"
    assert item["metadata"]["source_platform"] == "aliexpress"
    assert item["metadata"]["hot_product_commission_rate"] == "12%"
    assert item["metadata"]["shop_url"] == "https://aliexpress.com/store/777"


def test_ignores_product_without_price():
    raw = _raw_product(
        "1",
        target_app_sale_price="",
        target_sale_price="",
        app_sale_price="",
        sale_price="",
    )
    collector = _build_collector([raw])

    assert collector.collect() == []


def test_ignores_product_without_link():
    raw = _raw_product("1", product_detail_url=None, promotion_link=None)
    collector = _build_collector([raw])

    assert collector.collect() == []


def test_ignores_product_without_title():
    raw = _raw_product("1", product_title=None)
    collector = _build_collector([raw])

    assert collector.collect() == []
