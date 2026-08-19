import json
import time
from pathlib import Path

from app.collector_runner import collect_from_all_sources, collector_source_group
from app.persistence import migrate_legacy_sent_promotions, product_persistence_path


class ShopeeCollector:
    def __init__(self, items, delay=0.0):
        self._items = items
        self._delay = delay

    def collect(self):
        if self._delay:
            time.sleep(self._delay)
        return list(self._items)


class AliExpressCollector:
    def __init__(self, items, delay=0.0):
        self._items = items
        self._delay = delay

    def collect(self):
        if self._delay:
            time.sleep(self._delay)
        return list(self._items)


class AwinCollector:
    def __init__(self, items, delay=0.0, fail=False):
        self._items = items
        self._delay = delay
        self._fail = fail

    def collect(self):
        if self._fail:
            raise RuntimeError("awin down")
        if self._delay:
            time.sleep(self._delay)
        return list(self._items)


def test_awin_source_group():
    assert collector_source_group(AwinCollector([])) == "awin"


def test_awin_runs_in_parallel_with_other_sources():
    shopee = ShopeeCollector([{"id": "s1", "source": "shopee"}], delay=0.15)
    aliexpress = AliExpressCollector(
        [{"id": "a1", "source": "aliexpress"}], delay=0.15
    )
    awin = AwinCollector([{"id": "w1", "source": "awin"}], delay=0.15)

    started = time.perf_counter()
    items = collect_from_all_sources([shopee, aliexpress, awin])
    elapsed = time.perf_counter() - started

    assert {item["id"] for item in items} == {"s1", "a1", "w1"}
    assert elapsed < 0.35


def test_awin_failure_does_not_block_other_sources():
    items = collect_from_all_sources(
        [
            AwinCollector([], fail=True),
            ShopeeCollector([{"id": "s1", "source": "shopee"}]),
        ]
    )
    assert items == [{"id": "s1", "source": "shopee"}]


def test_migrate_legacy_sent_promotions_by_source(tmp_path: Path):
    legacy = tmp_path / "sent_promotions.json"
    legacy.write_text(
        json.dumps(
            {
                "sent_promotions": [
                    {
                        "offer_key": "shopee:offer:1",
                        "product_key": "shopee:product:1",
                        "product_price_key": "shopee:price:1",
                        "source": "shopee",
                        "external_id": "1",
                        "title": "A",
                        "price": 10,
                        "final_price": 10,
                        "coupon_code": None,
                        "payment_method": None,
                        "seller_id": None,
                        "is_official_store": None,
                        "free_shipping": None,
                        "sent_at": "2026-07-24T12:00:00+00:00",
                        "coupon_keys": [],
                    },
                    {
                        "offer_key": "aliexpress:offer:2",
                        "product_key": "aliexpress:product:2",
                        "product_price_key": "aliexpress:price:2",
                        "source": "aliexpress",
                        "external_id": "2",
                        "title": "B",
                        "price": 20,
                        "final_price": 20,
                        "coupon_code": None,
                        "payment_method": None,
                        "seller_id": None,
                        "is_official_store": None,
                        "free_shipping": None,
                        "sent_at": "2026-07-24T12:00:00+00:00",
                        "coupon_keys": [],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    migrate_legacy_sent_promotions(tmp_path)

    assert not legacy.exists()
    assert (tmp_path / "sent_promotions.json.migrated").exists()
    shopee_path = product_persistence_path(tmp_path, "shopee")
    aliexpress_path = product_persistence_path(tmp_path, "aliexpress")
    assert shopee_path.exists()
    assert aliexpress_path.exists()
    assert len(json.loads(shopee_path.read_text(encoding="utf-8"))["sent_promotions"]) == 1
    assert (
        len(json.loads(aliexpress_path.read_text(encoding="utf-8"))["sent_promotions"])
        == 1
    )
