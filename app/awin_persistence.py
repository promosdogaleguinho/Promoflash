import json
import logging
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from app.models import SentCampaignOfferSnapshot
from app.snapshot_retention import DEFAULT_RETAIN_HOURS, prune_snapshot_dicts

logger = logging.getLogger(__name__)

ROOT_KEY = "sent_awin_offers"


class AwinOfferPersistence:
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
        self._write_data({ROOT_KEY: []})

    def _read_data(self) -> dict:
        self._ensure_file_exists()
        try:
            with self._file_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            logger.error(
                "Histórico Awin inválido em %s (%s); reiniciando vazio",
                self._file_path.name,
                exc,
            )
            data = {ROOT_KEY: []}
            self._write_data(data)
            return data
        if not isinstance(data, dict):
            data = {ROOT_KEY: []}
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

    def load_snapshots(self) -> list[SentCampaignOfferSnapshot]:
        data = self._read_data()
        raw_items = list(data.get(ROOT_KEY, []))
        pruned = prune_snapshot_dicts(raw_items, self._retain_hours)
        if len(pruned) != len(raw_items):
            self._write_data({ROOT_KEY: pruned})
            logger.info(
                "Histórico Awin podado: %s -> %s (retain=%sh)",
                len(raw_items),
                len(pruned),
                self._retain_hours,
            )
        snapshots: list[SentCampaignOfferSnapshot] = []
        for item in pruned:
            if not isinstance(item, dict):
                continue
            try:
                snapshots.append(SentCampaignOfferSnapshot(**item))
            except TypeError as exc:
                logger.warning(
                    "Snapshot Awin inválido ignorado em %s: %s",
                    self._file_path.name,
                    exc,
                )
        return snapshots

    def add_snapshot(self, snapshot: SentCampaignOfferSnapshot) -> None:
        data = self._read_data()
        raw_items = list(data.get(ROOT_KEY, []))
        pruned = prune_snapshot_dicts(raw_items, self._retain_hours)
        pruned.append(asdict(snapshot))
        self._write_data({ROOT_KEY: pruned})
