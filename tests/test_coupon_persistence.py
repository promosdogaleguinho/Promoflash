import json
from datetime import datetime
from pathlib import Path

from app.coupon_lifecycle import get_timezone
from app.coupon_persistence import CouponCampaignPersistence
from app.coupon_repost_policy import build_campaign_snapshot
from app.models import Coupon, CouponCampaign, SentCouponCampaignSnapshot

TZ = get_timezone("America/Sao_Paulo")
NOW = datetime(2030, 1, 12, 12, 0, tzinfo=TZ)


def _campaign() -> CouponCampaign:
    return CouponCampaign(
        source="aliexpress",
        campaign_id="c1",
        title="Evento",
        coupons=[Coupon(source="aliexpress", code="EX01")],
    )


def test_creates_file_when_missing(tmp_path: Path):
    path = tmp_path / "sent_coupon_campaigns.json"
    persistence = CouponCampaignPersistence(str(path))

    assert persistence.load_snapshots() == []
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"sent_coupon_campaigns": []}


def test_does_not_erase_existing_history(tmp_path: Path):
    path = tmp_path / "sent_coupon_campaigns.json"
    existing = SentCouponCampaignSnapshot(
        publication_key="aliexpress:old",
        campaign_id="old",
        source="aliexpress",
        coupon_keys=["k"],
        published_at=NOW.isoformat(),
        content_fingerprint="fp-old",
    )
    persistence = CouponCampaignPersistence(str(path))
    persistence.add_snapshot(existing)

    persistence.add_snapshot(build_campaign_snapshot(_campaign(), ["chat1"], NOW))

    snapshots = persistence.load_snapshots()
    assert len(snapshots) == 2


def test_saves_sent_campaign(tmp_path: Path):
    path = tmp_path / "sent_coupon_campaigns.json"
    persistence = CouponCampaignPersistence(str(path))
    persistence.add_snapshot(build_campaign_snapshot(_campaign(), ["chat1"], NOW))

    snapshots = persistence.load_snapshots()
    assert snapshots[0].campaign_id == "c1"


def test_does_not_store_secrets(tmp_path: Path):
    path = tmp_path / "sent_coupon_campaigns.json"
    persistence = CouponCampaignPersistence(str(path))
    persistence.add_snapshot(build_campaign_snapshot(_campaign(), ["chat1"], NOW))

    content = path.read_text(encoding="utf-8")
    assert "token" not in content.lower()
    assert "secret" not in content.lower()
