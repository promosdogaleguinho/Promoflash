from datetime import datetime, timedelta, timezone

DEFAULT_RETAIN_HOURS = 24
_TIMESTAMP_KEYS = ("sent_at", "published_at")


def _parse_timestamp(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _item_timestamp(item: dict) -> datetime | None:
    for key in _TIMESTAMP_KEYS:
        parsed = _parse_timestamp(item.get(key))
        if parsed is not None:
            return parsed
    return None


def prune_snapshot_dicts(
    items: list[dict],
    retain_hours: int = DEFAULT_RETAIN_HOURS,
) -> list[dict]:
    if retain_hours <= 0:
        return list(items)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retain_hours)
    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        timestamp = _item_timestamp(item)
        if timestamp is not None and timestamp >= cutoff:
            kept.append(item)
    return kept
