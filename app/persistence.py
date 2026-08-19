import json
import logging
import os
import tempfile
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from app.models import SentPromotionSnapshot
from app.snapshot_retention import DEFAULT_RETAIN_HOURS, prune_snapshot_dicts

logger = logging.getLogger(__name__)

LEGACY_SENT_PROMOTIONS_FILE = "sent_promotions.json"
MIGRATED_SENT_PROMOTIONS_FILE = "sent_promotions.json.migrated"


def product_persistence_path(data_dir: Path | str, source: str) -> Path:
    safe_source = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in source.strip().lower()
    ) or "unknown"
    return Path(data_dir) / f"sent_promotions_{safe_source}.json"


def migrate_legacy_sent_promotions(data_dir: Path | str) -> None:
    """Divide sent_promotions.json legado por fonte, uma única vez.

    Após a divisão, o arquivo legado é renomeado para .migrated.
    Chamadas seguintes são no-op se o legado não existir.
    """
    root = Path(data_dir)
    legacy = root / LEGACY_SENT_PROMOTIONS_FILE
    if not legacy.exists():
        return

    try:
        with legacy.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Falha ao ler persistência legada de promoções: %s", exc)
        return

    by_source: dict[str, list[dict]] = defaultdict(list)
    for item in data.get("sent_promotions", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "unknown")
        by_source[source].append(item)

    for source, items in by_source.items():
        target = product_persistence_path(root, source)
        existing: list[dict] = []
        if target.exists():
            try:
                with target.open("r", encoding="utf-8") as file:
                    existing = list(
                        json.load(file).get("sent_promotions", [])
                    )
            except (OSError, json.JSONDecodeError):
                existing = []

        seen_keys = {
            item.get("offer_key")
            for item in existing
            if isinstance(item, dict) and item.get("offer_key")
        }
        merged = list(existing)
        for item in items:
            offer_key = item.get("offer_key")
            if offer_key and offer_key in seen_keys:
                continue
            if offer_key:
                seen_keys.add(offer_key)
            merged.append(item)

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as file:
            json.dump(
                {"sent_promotions": merged},
                file,
                ensure_ascii=False,
                indent=2,
            )

    migrated = root / MIGRATED_SENT_PROMOTIONS_FILE
    if migrated.exists():
        legacy.unlink(missing_ok=True)
    else:
        legacy.replace(migrated)

    logger.info(
        "Persistência de promoções migrada por fonte: %s",
        sorted(by_source.keys()),
    )


class JsonPersistence:
    def __init__(
        self,
        file_path: str,
        *,
        retain_hours: int = DEFAULT_RETAIN_HOURS,
    ) -> None:
        self._file_path = Path(file_path)
        self._retain_hours = retain_hours

    def _ensure_file_exists(self) -> None:
        if self._file_path.exists():
            return
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_data({"sent_promotions": []})

    def _read_data(self) -> dict:
        self._ensure_file_exists()
        try:
            with self._file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            logger.error(
                "Histórico inválido em %s (%s); reiniciando arquivo vazio",
                self._file_path.name,
                exc,
            )
            data = {"sent_promotions": []}
            self._write_data(data)
            return data
        if not isinstance(data, dict):
            data = {"sent_promotions": []}
            self._write_data(data)
        return data

    def _write_data(self, data: dict) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        directory = self._file_path.parent
        fd, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(data, temp_file, ensure_ascii=False, indent=2)
            os.replace(temp_path, self._file_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def _prune_and_maybe_persist(self, raw_items: list) -> list[dict]:
        pruned = prune_snapshot_dicts(raw_items, self._retain_hours)
        if len(pruned) != len(raw_items):
            self._write_data({"sent_promotions": pruned})
            logger.info(
                "Histórico podado em %s: %s -> %s (retain=%sh)",
                self._file_path.name,
                len(raw_items),
                len(pruned),
                self._retain_hours,
            )
        return pruned

    def load_snapshots(self) -> list[SentPromotionSnapshot]:
        data = self._read_data()
        raw_items = list(data.get("sent_promotions", []))
        pruned = self._prune_and_maybe_persist(raw_items)
        snapshots: list[SentPromotionSnapshot] = []
        for item in pruned:
            if not isinstance(item, dict):
                continue
            try:
                snapshots.append(SentPromotionSnapshot(**item))
            except TypeError as exc:
                logger.warning(
                    "Snapshot inválido ignorado em %s: %s",
                    self._file_path.name,
                    exc,
                )
        return snapshots

    def add_snapshot(self, snapshot: SentPromotionSnapshot) -> None:
        data = self._read_data()
        raw_items = list(data.get("sent_promotions", []))
        pruned = prune_snapshot_dicts(raw_items, self._retain_hours)
        pruned.append(asdict(snapshot))
        self._write_data({"sent_promotions": pruned})

    def save_snapshots(self, snapshots: list[SentPromotionSnapshot]) -> None:
        raw_items = [asdict(snapshot) for snapshot in snapshots]
        pruned = prune_snapshot_dicts(raw_items, self._retain_hours)
        self._write_data({"sent_promotions": pruned})
