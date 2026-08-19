from datetime import datetime, timedelta, timezone

from app.snapshot_retention import prune_snapshot_dicts


def test_prune_keeps_only_recent_snapshots():
    now = datetime.now(timezone.utc)
    items = [
        {"sent_at": (now - timedelta(hours=30)).isoformat(), "id": "old"},
        {"sent_at": (now - timedelta(hours=2)).isoformat(), "id": "new"},
        {"published_at": (now - timedelta(hours=50)).isoformat(), "id": "older"},
        {"published_at": (now - timedelta(hours=1)).isoformat(), "id": "fresh"},
        {"id": "no-timestamp"},
    ]

    kept = prune_snapshot_dicts(items, retain_hours=24)
    kept_ids = {item["id"] for item in kept}

    assert kept_ids == {"new", "fresh"}


def test_prune_disabled_when_retain_hours_zero():
    items = [{"sent_at": "2000-01-01T00:00:00+00:00", "id": "ancient"}]
    assert prune_snapshot_dicts(items, retain_hours=0) == items
