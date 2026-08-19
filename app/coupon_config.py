import json
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.coupon_lifecycle import DEFAULT_TIMEZONE, get_timezone
from app.models import Coupon, CouponCampaign, CouponDiscountType, CouponScopeType

logger = logging.getLogger(__name__)

COUPONS_FILENAME = "coupons.json"


def load_coupon_config(config_dir: str) -> dict:
    path = Path(config_dir) / COUPONS_FILENAME
    if not path.exists():
        return {"timezone": DEFAULT_TIMEZONE, "campaigns": [], "product_bindings": []}
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (ValueError, OSError) as exc:
        logger.warning("Falha ao ler config de cupons: %s", exc)
        return {"timezone": DEFAULT_TIMEZONE, "campaigns": [], "product_bindings": []}


def _parse_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: object, timezone_name: str) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.warning("Data de cupom inválida ignorada.")
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone(timezone_name))
    return parsed


def _parse_discount_type(value: object) -> CouponDiscountType:
    try:
        return CouponDiscountType(str(value))
    except ValueError:
        return CouponDiscountType.OTHER


def _parse_scope_type(value: object) -> CouponScopeType:
    try:
        return CouponScopeType(str(value))
    except ValueError:
        return CouponScopeType.UNKNOWN


def _build_coupon(
    data: dict,
    source: str,
    timezone_name: str,
    attachment_reason: str,
    campaign_id: str | None = None,
    campaign_name: str | None = None,
) -> Coupon:
    coins_amount = data.get("coins_amount")
    return Coupon(
        source=source,
        code=data.get("code"),
        title=data.get("title"),
        description=data.get("description"),
        discount_type=_parse_discount_type(data.get("discount_type")),
        discount_value=_parse_decimal(data.get("discount_value")),
        discount_percentage=_parse_decimal(data.get("discount_percentage")),
        minimum_spend=_parse_decimal(data.get("minimum_spend")),
        maximum_discount=_parse_decimal(data.get("maximum_discount")),
        start_at=_parse_datetime(data.get("start_at"), timezone_name),
        end_at=_parse_datetime(data.get("end_at"), timezone_name),
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        scope_type=_parse_scope_type(data.get("scope_type")),
        scope_value=data.get("scope_value"),
        app_only=bool(data.get("app_only", False)),
        requires_activation=bool(data.get("requires_activation", False)),
        requires_coupon_rescue=bool(data.get("requires_coupon_rescue", False)),
        requires_coins=bool(data.get("requires_coins", False)),
        coins_amount=int(coins_amount) if coins_amount is not None else None,
        payment_method=data.get("payment_method"),
        coupon_url=data.get("coupon_url"),
        affiliate_url=data.get("affiliate_url"),
        conditions=list(data.get("conditions", []) or []),
        metadata={
            "attachment_reason": attachment_reason,
            "source_collector": "manual_coupon_config",
        },
    )


def load_manual_coupon_campaigns(config: dict) -> list[CouponCampaign]:
    timezone_name = config.get("timezone", DEFAULT_TIMEZONE)
    campaigns: list[CouponCampaign] = []

    for entry in config.get("campaigns", []):
        if not entry.get("enabled", False):
            continue
        try:
            campaign = _build_campaign(entry, timezone_name)
        except Exception as exc:
            logger.warning(
                "Campanha manual ignorada (source=%s): %s",
                entry.get("source"),
                exc,
            )
            continue
        campaigns.append(campaign)

    return campaigns


def _build_campaign(entry: dict, timezone_name: str) -> CouponCampaign:
    source = entry["source"]
    campaign_id = entry["campaign_id"]
    coupons = [
        _build_coupon(
            coupon_data,
            source=source,
            timezone_name=timezone_name,
            attachment_reason="manual_campaign",
            campaign_id=campaign_id,
            campaign_name=entry.get("campaign_name"),
        )
        for coupon_data in entry.get("coupons", [])
    ]

    return CouponCampaign(
        source=source,
        campaign_id=campaign_id,
        title=entry["title"],
        description=entry.get("description"),
        campaign_name=entry.get("campaign_name"),
        coupons=coupons,
        affiliate_url=entry.get("affiliate_url"),
        campaign_url=entry.get("campaign_url"),
        image_url=entry.get("image_url"),
        category=entry.get("category"),
        tags=list(entry.get("tags", []) or []),
        start_at=_parse_datetime(entry.get("start_at"), timezone_name),
        end_at=_parse_datetime(entry.get("end_at"), timezone_name),
        announcement_at=_parse_datetime(entry.get("announcement_at"), timezone_name),
        announce_before_start=bool(entry.get("announce_before_start", False)),
        enabled=bool(entry.get("enabled", False)),
        metadata={"source_collector": "manual_coupon_config"},
    )


def load_manual_product_coupon_bindings(
    config: dict,
) -> dict[tuple[str, str], list[Coupon]]:
    timezone_name = config.get("timezone", DEFAULT_TIMEZONE)
    bindings: dict[tuple[str, str], list[Coupon]] = {}

    for entry in config.get("product_bindings", []):
        if not entry.get("enabled", False):
            continue
        source = entry.get("source")
        product_id = entry.get("external_product_id")
        coupon_data = entry.get("coupon")
        if not source or not product_id or not isinstance(coupon_data, dict):
            logger.warning("Binding manual de cupom inválido ignorado.")
            continue

        coupon = _build_coupon(
            coupon_data,
            source=source,
            timezone_name=timezone_name,
            attachment_reason="manual_product_binding",
        )
        bindings.setdefault((source, str(product_id)), []).append(coupon)

    return bindings
