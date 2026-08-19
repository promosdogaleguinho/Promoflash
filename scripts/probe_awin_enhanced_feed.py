"""Probe se o anunciante tem Enhanced Feed (Google Format) via API OAuth."""

from __future__ import annotations

import os
import sys
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
    advertiser_id = int(os.environ.get("AWIN_TEST_ADVERTISER_ID", "17729"))
    locales = [
        item.strip()
        for item in os.environ.get(
            "AWIN_FEED_LOCALE_CANDIDATES",
            "pt_BR,pt_PT,en_BR,en_GB,pt",
        ).split(",")
        if item.strip()
    ]

    if not token or not publisher_id:
        print("AWIN_OAUTH2_TOKEN / AWIN_PUBLISHER_ID ausentes")
        return 1

    from app.clients.awin import AwinClient

    client = AwinClient(oauth2_token=token, publisher_id=publisher_id)
    print(f"publisher={publisher_id} advertiser={advertiser_id}")
    for locale in locales:
        url = client.enhanced_feed_url(advertiser_id, locale)
        print(f"try locale={locale}")
        print(f"url={url}")
        try:
            content = client.fetch_enhanced_retail_feed(
                advertiser_id,
                locale=locale,
                timeout=90.0,
            )
        except Exception as exc:
            print(f"FAIL {type(exc).__name__}: {exc}")
            continue

        lines = [line for line in content.splitlines() if line.strip()]
        print(f"OK bytes={len(content)} lines={len(lines)}")
        if lines:
            sample = lines[0][:400]
            print(f"sample={sample!r}")
        return 0

    print("Nenhum Enhanced Feed encontrado para os locales testados.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
