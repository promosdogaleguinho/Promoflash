from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.awin_product_feed import (
    extract_landing_url,
    extract_merchant_product_id_from_url,
)
from app.text_encoding import fix_mojibake

SOURCE_AWIN = "awin"
KIND_VOUCHER = "voucher"
KIND_PROMOTION = "promotion"

ALLOWED_STATUSES = frozenset({"active", "expiringSoon"})
BRAZIL_COUNTRY_CODE = "BR"


@dataclass(frozen=True)
class AwinAdvertiserConfig:
    id: int
    name: str
    display_name: str
    enabled: bool = True


def parse_awin_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_region_applicable_to_brazil(regions: object) -> bool:
    if not isinstance(regions, dict):
        return False
    if regions.get("all") is True:
        return True
    region_list = regions.get("list")
    if not isinstance(region_list, list):
        return False
    for item in region_list:
        if not isinstance(item, dict):
            continue
        country = str(item.get("countryCode") or "").strip().upper()
        if country == BRAZIL_COUNTRY_CODE:
            return True
    return False


def _is_offer_active_now(
    start_at: datetime | None,
    end_at: datetime | None,
    now: datetime,
) -> bool:
    if start_at is not None and start_at > now:
        return False
    if end_at is not None and end_at <= now:
        return False
    return True


def map_awin_offer(
    raw: dict[str, Any],
    advertisers_by_id: dict[int, AwinAdvertiserConfig],
    now: datetime,
) -> tuple[dict[str, Any] | None, str | None]:
    """Mapeia oferta bruta da Awin para dict canônico.

    Retorna (item, motivo_rejeicao). item é None quando rejeitado.
    """
    if not isinstance(raw, dict):
        return None, "invalid_payload"

    advertiser = raw.get("advertiser")
    if not isinstance(advertiser, dict):
        return None, "missing_advertiser"

    try:
        advertiser_id = int(advertiser.get("id"))
    except (TypeError, ValueError):
        return None, "invalid_advertiser_id"

    if advertiser.get("joined") is not True:
        return None, "advertiser_not_joined"

    advertiser_config = advertisers_by_id.get(advertiser_id)
    if advertiser_config is None or not advertiser_config.enabled:
        return None, "advertiser_not_enabled"

    kind = str(raw.get("type") or "").strip().lower()
    if kind not in (KIND_VOUCHER, KIND_PROMOTION):
        return None, "unsupported_type"

    status = str(raw.get("status") or "").strip()
    if status not in ALLOWED_STATUSES:
        return None, "invalid_status"

    promotion_id = raw.get("promotionId")
    if promotion_id is None or str(promotion_id).strip() == "":
        return None, "missing_promotion_id"

    title = fix_mojibake(str(raw.get("title") or "").strip()) or ""
    if not title:
        return None, "missing_title"

    tracking_url = str(raw.get("urlTracking") or "").strip()
    if not tracking_url:
        return None, "missing_url_tracking"

    if not is_region_applicable_to_brazil(raw.get("regions")):
        return None, "region_not_br"

    start_at = parse_awin_datetime(raw.get("startDate"))
    end_at = parse_awin_datetime(raw.get("endDate"))
    if not _is_offer_active_now(start_at, end_at, now):
        return None, "outside_date_window"

    coupon_code: str | None = None
    if kind == KIND_VOUCHER:
        voucher = raw.get("voucher")
        if not isinstance(voucher, dict):
            return None, "missing_voucher"
        coupon_code = str(voucher.get("code") or "").strip() or None
        if not coupon_code:
            return None, "missing_voucher_code"

    description_raw = str(raw.get("description") or "").strip() or None
    description = fix_mojibake(description_raw)
    if description and description == title:
        description = None

    advertiser_name = (
        fix_mojibake(str(advertiser.get("name") or "").strip())
        or advertiser_config.name
    )

    raw_url = str(raw.get("url") or "").strip() or None
    landing_url = raw_url or extract_landing_url(tracking_url)
    merchant_product_id = extract_merchant_product_id_from_url(
        landing_url or tracking_url
    )

    return {
        "source": SOURCE_AWIN,
        "external_id": str(promotion_id).strip(),
        "kind": kind,
        "advertiser_id": str(advertiser_id),
        "advertiser_name": advertiser_name,
        "advertiser_display_name": advertiser_config.display_name,
        "title": title,
        "description": description,
        "coupon_code": coupon_code,
        "tracking_url": tracking_url,
        "url": tracking_url,
        "affiliate_url": tracking_url,
        "landing_url": landing_url,
        "merchant_product_id": merchant_product_id,
        "start_at": start_at.isoformat() if start_at else None,
        "end_at": end_at.isoformat() if end_at else None,
        "status": status,
        "category": None,
        "tags": [],
        "metadata": {
            "collector_type": "awin_offers",
            "source_platform": "awin",
            "advertiser_id": advertiser_id,
            "promotion_id": promotion_id,
            "raw_status": status,
            "raw_url": raw_url,
            "landing_url": landing_url,
            "merchant_product_id": merchant_product_id,
        },
    }, None
