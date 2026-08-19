import hashlib
import unicodedata
from datetime import datetime, timedelta

from app.models import CampaignOffer, SentCampaignOfferSnapshot

DEFAULT_WINDOW_HOURS = 24


def _normalize_token(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.split())


def build_offer_fingerprint(offer: CampaignOffer) -> str:
    price = "" if offer.price is None else f"{float(offer.price):.2f}"
    old_price = "" if offer.old_price is None else f"{float(offer.old_price):.2f}"
    parts = [
        _normalize_token(offer.kind),
        _normalize_token(offer.title),
        _normalize_token(offer.description),
        _normalize_token(offer.coupon_code),
        _normalize_token(offer.tracking_url),
        offer.start_at.isoformat() if offer.start_at else "",
        offer.end_at.isoformat() if offer.end_at else "",
        _normalize_token(offer.status),
        price,
        old_price,
        _normalize_token(offer.image_url),
    ]
    plain = "|".join(parts)
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def build_offer_destination_key(
    offer: CampaignOffer,
    destination: str,
) -> str:
    return (
        f"{_normalize_token(offer.source)}:"
        f"{_normalize_token(offer.advertiser_id)}:"
        f"{_normalize_token(offer.external_id)}:"
        f"{_normalize_token(destination)}"
    )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _within_window(published_at: str, now: datetime, window_hours: int) -> bool:
    published = _parse_datetime(published_at)
    if published.tzinfo is None and now.tzinfo is not None:
        published = published.replace(tzinfo=now.tzinfo)
    return published >= now - timedelta(hours=window_hours)


def should_send_offer_to_destination(
    offer: CampaignOffer,
    destination: str,
    snapshots: list[SentCampaignOfferSnapshot],
    now: datetime,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> bool:
    key = build_offer_destination_key(offer, destination)

    for snapshot in snapshots:
        if snapshot.offer_destination_key != key:
            continue
        if _within_window(snapshot.published_at, now, window_hours):
            return False
    return True


def build_offer_snapshot(
    offer: CampaignOffer,
    destination: str,
    now: datetime,
) -> SentCampaignOfferSnapshot:
    return SentCampaignOfferSnapshot(
        offer_destination_key=build_offer_destination_key(offer, destination),
        source=offer.source,
        advertiser_id=offer.advertiser_id,
        external_id=offer.external_id,
        destination=destination,
        kind=offer.kind,
        title=offer.title,
        content_fingerprint=build_offer_fingerprint(offer),
        published_at=now.isoformat(),
    )
