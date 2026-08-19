import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

SOURCE_SHOPEE = "shopee"
SOURCE_ALIEXPRESS = "aliexpress"
SOURCE_AWIN = "awin"
SOURCE_MOCK = "mock"


def collector_source_group(collector: object) -> str:
    name = type(collector).__name__.lower()
    if "shopee" in name:
        return SOURCE_SHOPEE
    if "aliexpress" in name:
        return SOURCE_ALIEXPRESS
    if "awin" in name:
        return SOURCE_AWIN
    if "mock" in name:
        return SOURCE_MOCK
    return type(collector).__name__


def _run_collector_group(source: str, collectors: list) -> tuple[str, list[dict]]:
    items: list[dict] = []
    for collector in collectors:
        collector_name = type(collector).__name__
        try:
            collected = collector.collect()
            items.extend(collected)
            logger.info(
                "Collector %s (source=%s) retornou %s itens",
                collector_name,
                source,
                len(collected),
            )
        except Exception as exc:
            logger.error(
                "Collector %s falhou e foi ignorado: %s",
                collector_name,
                exc,
            )
    return source, items


def collect_from_all_sources(collectors: list) -> list[dict]:
    """Coleta em paralelo entre fontes; dentro de cada fonte permanece sequencial."""
    if not collectors:
        return []

    groups: dict[str, list] = defaultdict(list)
    for collector in collectors:
        groups[collector_source_group(collector)].append(collector)

    if len(groups) == 1:
        source, group = next(iter(groups.items()))
        _, items = _run_collector_group(source, group)
        return items

    raw_items: list[dict] = []
    max_workers = min(len(groups), 4)
    logger.info(
        "Coleta paralela entre fontes: %s (workers=%s)",
        sorted(groups.keys()),
        max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(_run_collector_group, source, group_collectors)
            for source, group_collectors in groups.items()
        ]
        for future in as_completed(futures):
            source, items = future.result()
            raw_items.extend(items)
            logger.info(
                "Fonte %s finalizou coleta com %s itens",
                source,
                len(items),
            )

    return raw_items
