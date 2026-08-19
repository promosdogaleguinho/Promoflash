"""Sonda Offers API: contagem promotion/voucher por advertiser (KaBuM, Nike, C&A)."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_env_file() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def main() -> int:
    _load_env_file()
    token = (os.environ.get("AWIN_OAUTH2_TOKEN") or "").strip()
    publisher_id = (os.environ.get("AWIN_PUBLISHER_ID") or "").strip()
    if not token or not publisher_id:
        print("AWIN_OAUTH2_TOKEN / AWIN_PUBLISHER_ID ausentes")
        return 1

    sources = json.loads(
        (ROOT / "config" / "sources.json").read_text(encoding="utf-8")
    )
    awin = sources.get("awin") or {}
    advertisers = [
        item
        for item in (awin.get("advertisers") or [])
        if isinstance(item, dict) and item.get("enabled", True)
    ]
    advertiser_ids = [int(item["id"]) for item in advertisers]
    names = {
        int(item["id"]): str(item.get("display_name") or item.get("name") or item["id"])
        for item in advertisers
    }

    from app.clients.awin import AwinClient

    client = AwinClient(
        oauth2_token=token,
        publisher_id=publisher_id,
        page_size=int(awin.get("page_size") or 200),
    )
    print(f"publisher={publisher_id} advertiserIds={advertiser_ids}")

    items = client.fetch_promotions(
        advertiser_ids=advertiser_ids,
        membership=str(awin.get("membership") or "joined"),
        region_codes=list(awin.get("region_codes") or ["BR"]),
        status=str(awin.get("status") or "active"),
        offer_type=str(awin.get("type") or "all"),
    )
    print(f"pages={client.pages_fetched} total_offers={len(items)}")

    by_advertiser: dict[int, Counter] = {
        advertiser_id: Counter() for advertiser_id in advertiser_ids
    }
    unknown = Counter()

    for item in items:
        advertiser = item.get("advertiser") or {}
        try:
            advertiser_id = int(advertiser.get("id"))
        except (TypeError, ValueError):
            unknown["invalid_advertiser"] += 1
            continue
        kind = str(item.get("type") or "unknown").lower()
        if advertiser_id in by_advertiser:
            by_advertiser[advertiser_id][kind] += 1
            by_advertiser[advertiser_id]["total"] += 1
        else:
            unknown[f"other:{advertiser_id}:{kind}"] += 1

    print()
    print(f"{'Advertiser':<12} {'promotions':>12} {'vouchers':>12} {'total':>8}")
    for advertiser_id in advertiser_ids:
        counts = by_advertiser[advertiser_id]
        label = names.get(advertiser_id, str(advertiser_id))
        print(
            f"{label:<12} {counts.get('promotion', 0):>12} "
            f"{counts.get('voucher', 0):>12} {counts.get('total', 0):>8}"
        )

    if unknown:
        print()
        print("outros=", dict(unknown))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
