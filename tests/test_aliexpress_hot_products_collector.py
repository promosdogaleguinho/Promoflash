from unittest.mock import MagicMock

from app.collectors.aliexpress_hot_products import AliExpressHotProductsCollector


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
        "lastest_volume": "1500",
        "hot_product_commission_rate": "12%",
        "first_level_category_name": "Electronics",
    }
    base.update(overrides)
    return base


def _build_collector(products: list[dict], **config) -> AliExpressHotProductsCollector:
    client = MagicMock()
    client.hot_product_query.return_value = products
    source_config = {"max_items_per_run": 20, "page_size": 20}
    source_config.update(config)
    return AliExpressHotProductsCollector(client=client, source_config=source_config)


def test_hot_product_is_mapped():
    collector = _build_collector([_raw_product("1")])
    items = collector.collect()

    assert len(items) == 1
    assert items[0]["external_id"] == "1"
    assert items[0]["final_price"] == 79.90


def test_receives_produto_em_alta_tag():
    item = _build_collector([_raw_product("1")]).collect()[0]
    assert "Produto em alta" in item["promotion_tags"]


def test_receives_oferta_aliexpress_tag():
    item = _build_collector([_raw_product("1")]).collect()[0]
    assert "Oferta AliExpress" in item["promotion_tags"]


def test_not_official_campaign_automatically():
    item = _build_collector([_raw_product("1")]).collect()[0]
    assert item["is_official_campaign"] is False
    assert item["campaign_name"] is None


def test_metadata_has_collector_type():
    item = _build_collector([_raw_product("1")]).collect()[0]
    assert item["metadata"]["collector_type"] == "hot_products"
    assert item["metadata"]["source_platform"] == "aliexpress"


def test_removes_duplicates_by_product_id():
    collector = _build_collector(
        [_raw_product("1"), _raw_product("1"), _raw_product("2")]
    )
    external_ids = [item["external_id"] for item in collector.collect()]
    assert external_ids == ["1", "2"]


def test_respects_max_items_per_run():
    products = [_raw_product(str(i)) for i in range(10)]
    collector = _build_collector(products, max_items_per_run=3)
    assert len(collector.collect()) == 3


def test_empty_response_does_not_break():
    collector = _build_collector([])
    assert collector.collect() == []


def test_client_error_returns_empty_list():
    client = MagicMock()
    client.hot_product_query.side_effect = RuntimeError("boom")
    collector = AliExpressHotProductsCollector(
        client=client, source_config={"max_items_per_run": 20}
    )
    assert collector.collect() == []


def test_missing_image_does_not_invalidate_product():
    collector = _build_collector(
        [_raw_product("1", product_main_image_url=None, product_small_image_urls=None)]
    )
    items = collector.collect()
    assert len(items) == 1
    assert items[0]["image_url"] is None
