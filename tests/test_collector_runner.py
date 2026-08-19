import time

from app.collector_runner import (
    collect_from_all_sources,
    collector_source_group,
)


class ShopeeCollector:
    def __init__(self, items: list[dict], delay: float = 0.0) -> None:
        self._items = items
        self._delay = delay
        self.calls = 0

    def collect(self) -> list[dict]:
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        return list(self._items)


class AliExpressCollector:
    def __init__(self, items: list[dict], delay: float = 0.0) -> None:
        self._items = items
        self._delay = delay
        self.calls = 0

    def collect(self) -> list[dict]:
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        return list(self._items)


class AliExpressHotProductsCollector:
    def __init__(self, items: list[dict]) -> None:
        self._items = items
        self.calls = 0

    def collect(self) -> list[dict]:
        self.calls += 1
        return list(self._items)


class MockCollector:
    def collect(self) -> list[dict]:
        return []


class BoomShopeeCollector:
    def collect(self) -> list[dict]:
        raise RuntimeError("falha shopee")


def test_groups_shopee_and_aliexpress_by_class_name():
    assert collector_source_group(ShopeeCollector([])) == "shopee"
    assert collector_source_group(AliExpressHotProductsCollector([])) == "aliexpress"
    assert collector_source_group(MockCollector()) == "mock"


def test_single_source_stays_sequential():
    first = AliExpressCollector([{"id": "a1"}])
    second = AliExpressHotProductsCollector([{"id": "a2"}])

    items = collect_from_all_sources([first, second])
    assert [item["id"] for item in items] == ["a1", "a2"]
    assert first.calls == 1
    assert second.calls == 1


def test_sources_run_in_parallel():
    shopee = ShopeeCollector([{"id": "s1"}], delay=0.15)
    aliexpress = AliExpressCollector([{"id": "a1"}], delay=0.15)

    started = time.perf_counter()
    items = collect_from_all_sources([shopee, aliexpress])
    elapsed = time.perf_counter() - started

    assert {item["id"] for item in items} == {"s1", "a1"}
    assert elapsed < 0.28


def test_failure_in_one_source_does_not_block_other():
    items = collect_from_all_sources(
        [BoomShopeeCollector(), AliExpressCollector([{"id": "a1"}])]
    )
    assert items == [{"id": "a1"}]
