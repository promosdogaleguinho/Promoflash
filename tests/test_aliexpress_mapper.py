from app.collectors.aliexpress_mapper import map_aliexpress_product


def _raw_product(product_id: str = "1", **overrides) -> dict:
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


def test_maps_price_correctly():
    mapped = map_aliexpress_product(_raw_product())
    assert mapped["final_price"] == 79.90
    assert mapped["price"] == 79.90


def test_keeps_target_app_sale_price_priority():
    mapped = map_aliexpress_product(_raw_product())
    assert mapped["metadata"]["price_source"] == "target_app_sale_price"


def test_uses_target_sale_price_as_fallback():
    mapped = map_aliexpress_product(_raw_product(target_app_sale_price=""))
    assert mapped["final_price"] == 89.90
    assert mapped["metadata"]["price_source"] == "target_sale_price"


def test_uses_promotion_link_as_affiliate_url():
    promo = "https://s.click.aliexpress.com/e/custom"
    mapped = map_aliexpress_product(_raw_product(promotion_link=promo))
    assert mapped["affiliate_url"] == promo
    assert mapped["url"] == "https://aliexpress.com/item/1.html"


def test_maps_main_image():
    mapped = map_aliexpress_product(_raw_product())
    assert mapped["image_url"] == "https://img.aliexpress.com/1.jpg"


def test_uses_secondary_image_as_fallback():
    raw = _raw_product(
        product_main_image_url=None,
        product_small_image_urls={"string": ["", "https://img/second.jpg"]},
    )
    mapped = map_aliexpress_product(raw)
    assert mapped["image_url"] == "https://img/second.jpg"


def test_accepts_small_images_as_direct_list():
    raw = _raw_product(
        product_main_image_url=None,
        product_small_image_urls=["https://img/direct.jpg"],
    )
    mapped = map_aliexpress_product(raw)
    assert mapped["image_url"] == "https://img/direct.jpg"


def test_item_without_image_still_valid():
    raw = _raw_product(product_main_image_url=None, product_small_image_urls=None)
    mapped = map_aliexpress_product(raw)
    assert mapped is not None
    assert mapped["image_url"] is None


def test_item_without_price_is_rejected():
    raw = _raw_product(
        target_app_sale_price="",
        target_sale_price="",
        app_sale_price="",
        sale_price="",
    )
    assert map_aliexpress_product(raw) is None


def test_item_without_link_is_rejected():
    raw = _raw_product(product_detail_url=None, promotion_link=None)
    assert map_aliexpress_product(raw) is None


def test_item_without_title_is_rejected():
    assert map_aliexpress_product(_raw_product(product_title=None)) is None


def test_item_without_id_is_rejected():
    assert map_aliexpress_product(_raw_product(product_id=None)) is None


def test_extra_metadata_is_merged():
    mapped = map_aliexpress_product(
        _raw_product(),
        extra_metadata={"campaign_id": "c-1", "collector_type": "featured_promotions"},
    )
    assert mapped["metadata"]["campaign_id"] == "c-1"
    assert mapped["metadata"]["collector_type"] == "featured_promotions"
    assert mapped["metadata"]["raw"]["product_id"] == "1"


def test_extra_tags_are_preserved():
    mapped = map_aliexpress_product(
        _raw_product(),
        extra_tags=["Produto em alta", "Oferta AliExpress"],
    )
    assert "Produto em alta" in mapped["promotion_tags"]
    assert "Oferta AliExpress" in mapped["promotion_tags"]


def test_does_not_duplicate_tags():
    mapped = map_aliexpress_product(
        _raw_product(),
        campaign_name="Oferta da semana",
        is_official_campaign=True,
        extra_tags=["Oferta da semana", "Oferta da semana"],
    )
    assert mapped["promotion_tags"].count("Oferta da semana") == 1


def test_sanitizes_internal_campaign_detected_in_product():
    mapped = map_aliexpress_product(
        _raw_product(promotion_name="AEB_BR_ShipFromBR_20241114")
    )
    assert mapped["campaign_name"] == "Envio do Brasil"
    assert "AEB_BR_ShipFromBR_20241114" not in mapped["promotion_tags"]


def test_price_link_image_belong_to_same_item():
    mapped = map_aliexpress_product(_raw_product("42"))
    assert mapped["external_id"] == "42"
    assert "42" in mapped["url"]
    assert "42" in mapped["affiliate_url"]
    assert "42" in mapped["image_url"]


def test_old_price_lower_than_final_becomes_none():
    raw = _raw_product(target_original_price="70.00", original_price="60.00")
    mapped = map_aliexpress_product(raw)
    assert mapped["old_price"] is None


def test_collector_type_is_recorded():
    mapped = map_aliexpress_product(_raw_product(), collector_type="hot_products")
    assert mapped["metadata"]["collector_type"] == "hot_products"


def test_non_dict_item_returns_none():
    assert map_aliexpress_product(None) is None
    assert map_aliexpress_product("invalid") is None
