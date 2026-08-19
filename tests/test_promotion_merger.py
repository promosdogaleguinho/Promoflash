from app.models import Promotion
from app.promotion_merger import merge_duplicate_promotions


def _promotion(external_id: str, **overrides) -> Promotion:
    defaults = {
        "external_id": external_id,
        "source": "aliexpress",
        "title": f"Produto {external_id}",
        "url": f"https://aliexpress.com/item/{external_id}.html",
        "affiliate_url": f"https://s.click.aliexpress.com/e/{external_id}",
        "final_price": 100.0,
        "image_url": f"https://img/{external_id}.jpg",
        "metadata": {"collector_type": "product_search"},
    }
    defaults.update(overrides)
    return Promotion(**defaults)


def test_duplicates_between_collectors_are_merged():
    hot = _promotion("1", metadata={"collector_type": "hot_products"})
    search = _promotion("1", metadata={"collector_type": "product_search"})
    merged = merge_duplicate_promotions([hot, search])
    assert len(merged) == 1


def test_tags_are_merged_without_duplication():
    a = _promotion("1", promotion_tags=["Oferta AliExpress", "Produto em alta"])
    b = _promotion("1", promotion_tags=["Oferta AliExpress", "Desconto"])
    merged = merge_duplicate_promotions([a, b])[0]
    assert merged.promotion_tags.count("Oferta AliExpress") == 1
    assert "Produto em alta" in merged.promotion_tags
    assert "Desconto" in merged.promotion_tags


def test_official_campaign_prevails():
    plain = _promotion(
        "1", final_price=90.0, metadata={"collector_type": "hot_products"}
    )
    official = _promotion(
        "1",
        final_price=110.0,
        is_official_campaign=True,
        campaign_name="Oferta da semana",
        metadata={"collector_type": "featured_promotions"},
    )
    merged = merge_duplicate_promotions([plain, official])[0]
    assert merged.is_official_campaign is True
    assert merged.campaign_name == "Oferta da semana"


def test_campaign_name_is_preserved():
    official = _promotion(
        "1", is_official_campaign=True, campaign_name="Choice Day"
    )
    plain = _promotion("1")
    merged = merge_duplicate_promotions([plain, official])[0]
    assert merged.campaign_name == "Choice Day"


def test_collector_types_contains_all():
    a = _promotion("1", metadata={"collector_type": "hot_products"})
    b = _promotion("1", metadata={"collector_type": "featured_promotions"})
    c = _promotion("1", metadata={"collector_type": "product_search"})
    merged = merge_duplicate_promotions([a, b, c])[0]
    assert set(merged.metadata["collector_types"]) == {
        "hot_products",
        "featured_promotions",
        "product_search",
    }


def test_campaign_names_contains_all():
    a = _promotion("1", campaign_name="Choice Day", is_official_campaign=True)
    b = _promotion("1", campaign_name="Oferta da semana", is_official_campaign=True)
    merged = merge_duplicate_promotions([a, b])[0]
    assert set(merged.metadata["campaign_names"]) == {"Choice Day", "Oferta da semana"}


def test_lower_price_defines_base():
    cheap = _promotion("1", final_price=80.0, image_url="https://img/cheap.jpg")
    expensive = _promotion("1", final_price=120.0, image_url="https://img/exp.jpg")
    merged = merge_duplicate_promotions([expensive, cheap])[0]
    assert merged.final_price == 80.0
    assert merged.image_url == "https://img/cheap.jpg"


def test_price_link_image_stay_from_same_version():
    a = _promotion(
        "1",
        final_price=80.0,
        affiliate_url="https://link/a",
        image_url="https://img/a.jpg",
    )
    b = _promotion(
        "1",
        final_price=120.0,
        affiliate_url="https://link/b",
        image_url="https://img/b.jpg",
    )
    merged = merge_duplicate_promotions([b, a])[0]
    assert merged.final_price == 80.0
    assert merged.affiliate_url == "https://link/a"
    assert merged.image_url == "https://img/a.jpg"


def test_prefers_version_with_affiliate_url():
    without = _promotion("1", affiliate_url=None, final_price=70.0)
    with_link = _promotion("1", affiliate_url="https://link/ok", final_price=90.0)
    merged = merge_duplicate_promotions([without, with_link])[0]
    assert merged.affiliate_url == "https://link/ok"


def test_non_duplicated_promotion_is_unchanged():
    single = _promotion("1")
    merged = merge_duplicate_promotions([single])
    assert merged == [single]


def test_higher_score_is_preserved():
    low = _promotion("1", promotion_score=10.0)
    high = _promotion("1", promotion_score=55.0)
    merged = merge_duplicate_promotions([low, high])[0]
    assert merged.promotion_score == 55.0


def test_one_promotion_per_source_and_external_id():
    promotions = [_promotion("1"), _promotion("1"), _promotion("2")]
    merged = merge_duplicate_promotions(promotions)
    assert len(merged) == 2


def test_groups_by_product_key_when_no_external_id():
    a = _promotion("", product_key="aliexpress:product:abc")
    b = _promotion("", product_key="aliexpress:product:abc")
    merged = merge_duplicate_promotions([a, b])
    assert len(merged) == 1
