from app.clients.shopee_affiliate import ShopeeAffiliateClient
from app.collectors.shopee import ShopeeCollector
from app.collectors.shopee_mapper import PERIOD_OPEN_ENDED_SENTINEL


def _node(item_id: int, shop_id: int = 100, **overrides) -> dict:
    base = {
        "itemId": item_id,
        "productName": f"Produto {item_id}",
        "price": "49.99",
        "priceMin": "49.99",
        "priceMax": "49.99",
        "priceDiscountRate": "15",
        "sales": 10,
        "imageUrl": "https://cf.shopee.com.br/file/x.jpg",
        "shopName": "Loja",
        "shopId": shop_id,
        "shopType": [],
        "productLink": f"https://shopee.com.br/product/{shop_id}/{item_id}",
        "offerLink": f"https://s.shopee.com.br/offer-{item_id}",
        "periodStartTime": 1700000000,
        "periodEndTime": PERIOD_OPEN_ENDED_SENTINEL,
        "productCatIds": [1],
        "ratingStar": "4.5",
        "commissionRate": "0.05",
        "commission": "1.00",
    }
    base.update(overrides)
    return base


class FakeShopeeClient(ShopeeAffiliateClient):
    def __init__(self, pages: dict[int, dict]):
        super().__init__(app_id="app", app_secret="secret", page_limit=20)
        self._pages = pages
        self.calls: list[tuple[str | None, int, int]] = []

    def product_offer_v2(self, keyword=None, page=1, limit=None):
        self.calls.append((keyword, page, limit or self.page_limit))
        return self._pages.get(
            page,
            {
                "nodes": [],
                "pageInfo": {
                    "page": page,
                    "limit": limit or self.page_limit,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            },
        )


def test_empty_page_stops():
    client = FakeShopeeClient(
        {
            1: {
                "nodes": [],
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            }
        }
    )
    collector = ShopeeCollector(client=client, keywords=["fone"], max_pages=5)
    assert collector.collect() == []
    assert collector.metrics.pages_fetched == 1


def test_multiple_pages_until_has_next_false():
    client = FakeShopeeClient(
        {
            1: {
                "nodes": [_node(1), _node(2)],
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            },
            2: {
                "nodes": [_node(3)],
                "pageInfo": {
                    "page": 2,
                    "limit": 20,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            },
        }
    )
    collector = ShopeeCollector(
        client=client,
        keywords=["notebook"],
        max_items_per_run=20,
        max_pages=5,
    )
    items = collector.collect()
    assert len(items) == 3
    assert collector.metrics.pages_fetched == 2
    assert [call[1] for call in client.calls] == [1, 2]


def test_max_pages_respected():
    pages = {
        page: {
            "nodes": [_node(page)],
            "pageInfo": {
                "page": page,
                "limit": 20,
                "hasNextPage": True,
                "scrollId": None,
            },
        }
        for page in range(1, 10)
    }
    client = FakeShopeeClient(pages)
    collector = ShopeeCollector(
        client=client,
        keywords=["tv"],
        max_items_per_run=50,
        max_pages=3,
    )
    items = collector.collect()
    assert len(items) == 3
    assert collector.metrics.pages_fetched == 3


def test_repeated_page_protection():
    same_nodes = [_node(10), _node(11)]
    client = FakeShopeeClient(
        {
            1: {
                "nodes": same_nodes,
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            },
            2: {
                "nodes": same_nodes,
                "pageInfo": {
                    "page": 2,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            },
        }
    )
    collector = ShopeeCollector(
        client=client,
        keywords=["mouse"],
        max_items_per_run=50,
        max_pages=5,
    )
    items = collector.collect()
    assert len(items) == 2
    assert collector.metrics.pages_fetched == 2


def test_duplicate_products_across_pages():
    client = FakeShopeeClient(
        {
            1: {
                "nodes": [_node(1), _node(2)],
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            },
            2: {
                "nodes": [_node(2), _node(3)],
                "pageInfo": {
                    "page": 2,
                    "limit": 20,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            },
        }
    )
    collector = ShopeeCollector(
        client=client,
        keywords=["ssd"],
        max_items_per_run=20,
        max_pages=5,
    )
    items = collector.collect()
    assert len(items) == 3
    assert collector.metrics.duplicates_across_pages == 1


def test_twenty_products_has_next_page():
    nodes = [_node(i) for i in range(1, 21)]
    client = FakeShopeeClient(
        {
            1: {
                "nodes": nodes,
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": True,
                    "scrollId": None,
                },
            },
            2: {
                "nodes": [_node(21)],
                "pageInfo": {
                    "page": 2,
                    "limit": 20,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            },
        }
    )
    collector = ShopeeCollector(
        client=client,
        keywords=["perfume"],
        max_items_per_run=25,
        max_pages=5,
    )
    items = collector.collect()
    assert len(items) == 21
    assert collector.metrics.nodes_received == 21


def test_without_offer_link_metric():
    client = FakeShopeeClient(
        {
            1: {
                "nodes": [_node(1, offerLink=None), _node(2)],
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            }
        }
    )
    collector = ShopeeCollector(client=client, keywords=["cabo"], max_pages=1)
    items = collector.collect()
    assert len(items) == 1
    assert collector.metrics.products_without_offer_link == 1
    assert collector.metrics.rejection_reasons.get("sem_offer_link") == 1


def test_keyword_quota_does_not_starve_later_keywords():
    class KeywordClient(ShopeeAffiliateClient):
        def __init__(self):
            super().__init__(app_id="app", app_secret="secret", page_limit=20)
            self.calls: list[str | None] = []

        def product_offer_v2(self, keyword=None, page=1, limit=None):
            self.calls.append(keyword)
            item_id = 1000 + len(self.calls)
            return {
                "nodes": [
                    _node(item_id, productName=f"Produto {keyword or 'none'} {item_id}")
                ],
                "pageInfo": {
                    "page": 1,
                    "limit": 20,
                    "hasNextPage": False,
                    "scrollId": None,
                },
            }

    client = KeywordClient()
    collector = ShopeeCollector(
        client=client,
        keywords=["notebook", "conjunto academia", "vestido"],
        max_items_per_run=3,
        max_pages=1,
    )
    items = collector.collect()
    assert len(items) == 3
    assert client.calls == ["notebook", "conjunto academia", "vestido"]
