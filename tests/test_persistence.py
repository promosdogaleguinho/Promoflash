import json
from pathlib import Path

from app.persistence import JsonPersistence


def test_creates_empty_file_when_missing(tmp_path: Path) -> None:
    file_path = tmp_path / "sent_promotions.json"
    persistence = JsonPersistence(str(file_path))

    snapshots = persistence.load_snapshots()

    assert snapshots == []
    assert file_path.exists()
    data = json.loads(file_path.read_text(encoding="utf-8"))
    assert data == {"sent_promotions": []}
