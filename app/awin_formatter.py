from decimal import Decimal

from app.models import CampaignOffer, FormattedMessage, MessageAction

VOUCHER_BUTTON_TEXT = "🎟️ Acessar cupom"
PROMOTION_BUTTON_TEXT = "🔥 Ver oferta"


def _format_brl(value: float | Decimal) -> str:
    formatted = f"{float(value):,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _price_lines(offer: CampaignOffer) -> list[str]:
    if offer.price is None:
        return []
    if offer.old_price is not None and offer.old_price > offer.price:
        return [
            f"De: {_format_brl(offer.old_price)}",
            f"Por: {_format_brl(offer.price)}",
        ]
    return [f"Por: {_format_brl(offer.price)}"]


def format_campaign_offer(offer: CampaignOffer) -> FormattedMessage:
    display_name = offer.advertiser_display_name or offer.advertiser_name or "Parceiro"
    price_block = _price_lines(offer)

    if offer.kind == "voucher":
        lines = [
            f"🎟️ Cupom {display_name}",
            "",
            offer.title,
        ]
        if price_block:
            lines.extend(["", *price_block])
        lines.extend(["", f"Cupom: {offer.coupon_code}"])
        button_text = VOUCHER_BUTTON_TEXT
        action_type = "coupon"
    else:
        lines = [
            f"🔥 Oferta {display_name}",
            "",
            offer.title,
        ]
        if price_block:
            lines.extend(["", *price_block])
        button_text = PROMOTION_BUTTON_TEXT
        action_type = "offer"

    return FormattedMessage(
        text="\n".join(lines).strip(),
        image_url=offer.image_url or None,
        offer_url=offer.tracking_url,
        button_text=button_text,
        actions=[
            MessageAction(
                text=button_text,
                url=offer.tracking_url,
                action_type=action_type,
            )
        ],
    )


def campaign_offer_from_dict(item: dict) -> CampaignOffer:
    from datetime import datetime

    def _parse_dt(value: object) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    def _parse_float(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    return CampaignOffer(
        source=str(item["source"]),
        external_id=str(item["external_id"]),
        kind=str(item["kind"]),
        advertiser_id=str(item["advertiser_id"]),
        advertiser_name=str(item.get("advertiser_name") or ""),
        advertiser_display_name=str(item.get("advertiser_display_name") or ""),
        title=str(item["title"]),
        tracking_url=str(
            item.get("tracking_url")
            or item.get("affiliate_url")
            or item.get("url")
            or ""
        ),
        description=item.get("description"),
        coupon_code=item.get("coupon_code"),
        start_at=_parse_dt(item.get("start_at")),
        end_at=_parse_dt(item.get("end_at")),
        status=item.get("status"),
        category=item.get("category"),
        resolved_category=item.get("resolved_category"),
        tags=list(item.get("tags") or []),
        metadata=dict(item.get("metadata") or {}),
        price=_parse_float(item.get("price")),
        old_price=_parse_float(item.get("old_price")),
        image_url=item.get("image_url"),
        currency=item.get("currency"),
        merchant_product_id=(
            str(item["merchant_product_id"])
            if item.get("merchant_product_id") is not None
            else None
        ),
    )
