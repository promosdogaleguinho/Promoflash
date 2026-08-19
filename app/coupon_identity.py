import hashlib
import unicodedata

from app.models import Coupon, CouponCampaign

_MAX_PLAIN_KEY_LENGTH = 120


def _normalize_token(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.split())


def _scope_token(coupon: Coupon) -> str:
    scope_type = coupon.scope_type.value if coupon.scope_type else ""
    return f"{scope_type}:{_normalize_token(coupon.scope_value)}"


def _discount_token(coupon: Coupon) -> str:
    discount_type = coupon.discount_type.value if coupon.discount_type else ""
    value = coupon.discount_value if coupon.discount_value is not None else ""
    percentage = (
        coupon.discount_percentage if coupon.discount_percentage is not None else ""
    )
    return f"{discount_type}:{value}:{percentage}"


def _limits_token(coupon: Coupon) -> str:
    minimum = coupon.minimum_spend if coupon.minimum_spend is not None else ""
    maximum = coupon.maximum_discount if coupon.maximum_discount is not None else ""
    return f"{minimum}:{maximum}"


def _validity_token(coupon: Coupon) -> str:
    start = coupon.start_at.isoformat() if coupon.start_at else ""
    end = coupon.end_at.isoformat() if coupon.end_at else ""
    return f"{start}:{end}"


def build_coupon_key(coupon: Coupon) -> str:
    parts = [
        _normalize_token(coupon.source),
        _normalize_token(coupon.code),
        _normalize_token(coupon.campaign_id),
        _normalize_token(coupon.campaign_name),
        _scope_token(coupon),
        _discount_token(coupon),
        _limits_token(coupon),
        _validity_token(coupon),
    ]
    plain_key = "|".join(parts)

    if len(plain_key) <= _MAX_PLAIN_KEY_LENGTH:
        return plain_key

    digest = hashlib.sha256(plain_key.encode("utf-8")).hexdigest()[:16]
    return f"{_normalize_token(coupon.source)}|{digest}"


def build_campaign_fingerprint(campaign: CouponCampaign) -> str:
    coupon_keys = sorted(build_coupon_key(coupon) for coupon in campaign.coupons)
    parts = [
        _normalize_token(campaign.source),
        _normalize_token(campaign.campaign_id),
        _normalize_token(campaign.title),
        _normalize_token(campaign.description),
        campaign.start_at.isoformat() if campaign.start_at else "",
        campaign.end_at.isoformat() if campaign.end_at else "",
        "||".join(coupon_keys),
    ]
    plain = "|".join(parts)
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def build_publication_key(campaign: CouponCampaign) -> str:
    return f"{_normalize_token(campaign.source)}:{_normalize_token(campaign.campaign_id)}"
