from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from app.coupon_identity import build_coupon_key
from app.models import Promotion, SentPromotionSnapshot
from app.product_identity import (
    build_offer_key,
    build_product_key,
    build_product_price_key,
    normalize_text,
)

DEFAULT_MIN_PRICE_DROP_ABSOLUTE = 5.0
DEFAULT_MIN_PRICE_DROP_PERCENT = 0.05
DEFAULT_TITLE_SIMILARITY_THRESHOLD = 0.85


def _coupon_keys(promotion: Promotion) -> set[str]:
    return {build_coupon_key(coupon) for coupon in promotion.coupons}


def _parse_sent_at(sent_at: str) -> datetime:
    return datetime.fromisoformat(sent_at.replace("Z", "+00:00"))


def _within_window(sent_at: str, repost_window_hours: int) -> bool:
    sent_time = _parse_sent_at(sent_at)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=repost_window_hours)
    if sent_time.tzinfo is None:
        sent_time = sent_time.replace(tzinfo=timezone.utc)
    return sent_time >= cutoff


def _effective_price(promotion: Promotion | SentPromotionSnapshot) -> float | None:
    if promotion.final_price is not None:
        return promotion.final_price
    return promotion.price


def _price_bucket(final_price: float | None, price: float | None = None) -> str:
    effective = final_price if final_price is not None else price
    if effective is None:
        return "unknown-price"
    return str(int(round(effective * 100)))


def build_title_price_key(
    source: str,
    title: str | None,
    final_price: float | None,
    price: float | None = None,
) -> str:
    normalized_title = normalize_text(title or "") or "sem-titulo"
    return (
        f"{source}:title-price:{normalized_title}:"
        f"{_price_bucket(final_price, price)}"
    )


def titles_are_equivalent(
    left: str | None,
    right: str | None,
    *,
    threshold: float = DEFAULT_TITLE_SIMILARITY_THRESHOLD,
) -> bool:
    left_norm = normalize_text(left or "")
    right_norm = normalize_text(right or "")
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    if SequenceMatcher(None, left_norm, right_norm).ratio() >= threshold:
        return True

    left_tokens = set(left_norm.replace("-", " ").split())
    right_tokens = set(right_norm.replace("-", " ").split())
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return overlap >= threshold


def is_same_title_and_price(
    left_title: str | None,
    left_final: float | None,
    left_price: float | None,
    right_title: str | None,
    right_final: float | None,
    right_price: float | None,
) -> bool:
    if _price_bucket(left_final, left_price) != _price_bucket(right_final, right_price):
        return False
    return titles_are_equivalent(left_title, right_title)


def _is_meaningful_price_drop(
    current_price: float | None,
    previous_price: float | None,
    *,
    min_absolute: float = DEFAULT_MIN_PRICE_DROP_ABSOLUTE,
    min_percent: float = DEFAULT_MIN_PRICE_DROP_PERCENT,
) -> bool:
    if current_price is None or previous_price is None:
        return False
    if current_price >= previous_price:
        return False
    drop = previous_price - current_price
    threshold = max(min_absolute, previous_price * min_percent)
    return drop >= threshold


def _find_latest_by_product_key(
    product_key: str,
    snapshots: list[SentPromotionSnapshot],
) -> SentPromotionSnapshot | None:
    matching = [
        snapshot for snapshot in snapshots if snapshot.product_key == product_key
    ]
    if not matching:
        return None
    return max(matching, key=lambda snapshot: _parse_sent_at(snapshot.sent_at))


def should_send_promotion(
    promotion: Promotion,
    sent_snapshots: list[SentPromotionSnapshot],
    repost_window_hours: int,
) -> bool:
    offer_key = build_offer_key(promotion)
    product_key = build_product_key(promotion)
    product_price_key = build_product_price_key(promotion)

    recent_snapshots = [
        snapshot
        for snapshot in sent_snapshots
        if _within_window(snapshot.sent_at, repost_window_hours)
    ]

    current_coupon_keys = _coupon_keys(promotion)
    is_sku_offer = isinstance(
        (promotion.metadata or {}).get("sku_offer_group"), dict
    )

    for snapshot in recent_snapshots:
        if snapshot.offer_key == offer_key:
            previous_coupon_keys = set(snapshot.coupon_keys or [])
            if current_coupon_keys - previous_coupon_keys:
                return True
            return False

    for snapshot in recent_snapshots:
        if titles_are_equivalent(promotion.title, snapshot.title):
            if _is_meaningful_price_drop(
                _effective_price(promotion),
                _effective_price(snapshot),
            ):
                return True
            return False

    product_snapshots = [
        snapshot
        for snapshot in recent_snapshots
        if snapshot.product_key == product_key
    ]
    if not product_snapshots:
        return True

    latest = _find_latest_by_product_key(product_key, product_snapshots)
    if latest is None:
        return True

    if _is_meaningful_price_drop(
        _effective_price(promotion),
        _effective_price(latest),
    ):
        return True

    previous_coupon_keys = set(latest.coupon_keys or [])
    if current_coupon_keys - previous_coupon_keys:
        return True

    if promotion.free_shipping and not latest.free_shipping:
        return True

    if promotion.is_official_store and not latest.is_official_store:
        return True

    if not is_sku_offer and promotion.coupon_code and not latest.coupon_code:
        return True

    if not is_sku_offer:
        for snapshot in recent_snapshots:
            if snapshot.product_price_key == product_price_key:
                return False

    return False


def build_sent_snapshot(promotion: Promotion) -> SentPromotionSnapshot:
    return SentPromotionSnapshot(
        offer_key=build_offer_key(promotion),
        product_key=build_product_key(promotion),
        product_price_key=build_product_price_key(promotion),
        source=promotion.source,
        external_id=promotion.external_id,
        title=promotion.title,
        price=promotion.price,
        final_price=promotion.final_price,
        coupon_code=promotion.coupon_code,
        payment_method=promotion.payment_method,
        seller_id=promotion.seller_id,
        is_official_store=promotion.is_official_store,
        free_shipping=promotion.free_shipping,
        sent_at=datetime.now(timezone.utc).isoformat(),
        coupon_keys=sorted(_coupon_keys(promotion)),
    )
