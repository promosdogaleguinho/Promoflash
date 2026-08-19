from datetime import datetime
from decimal import Decimal

from app.campaigns import (
    DISPLAY_BEST_SELLER,
    DISPLAY_HOT_PRODUCT,
    DISPLAY_NEW_ARRIVAL,
    DISPLAY_WEEKLY_DEALS,
)
from app.coupon_lifecycle import now_in_timezone
from app.coupon_render import build_product_coupon_lines, select_display_coupons
from app.models import Coupon, FormattedMessage, MessageAction, Promotion
from app.promotion_quality import (
    SOURCE_ALIEXPRESS,
    SOURCE_SHOPEE,
    TAG_ALIEXPRESS,
    TAG_DISCOUNT,
    TAG_OFFICIAL_CAMPAIGN,
    TAG_SHOPEE,
)

DEFAULT_BUTTON_TEXT = "🛒 Ver oferta"
PRODUCT_BUTTON_TEXT = "🛒 Ver produto"
COUPON_BUTTON_TEXT = "🎟️ Resgatar cupom"
MORE_COUPONS_TEXT = "Outros cupons podem estar disponíveis na página da oferta."

MAX_DISPLAY_TAGS = 3
MAX_PRODUCT_COUPONS = 2
_EMPTY_VARIATION_LABELS = {
    "",
    "padrão",
    "padrao",
    "default",
    "standard",
    "cor",
    "color",
    "tamanho",
    "size",
}

_TAG_PRIORITY = (
    TAG_OFFICIAL_CAMPAIGN,
    DISPLAY_WEEKLY_DEALS,
    DISPLAY_HOT_PRODUCT,
    DISPLAY_NEW_ARRIVAL,
    DISPLAY_BEST_SELLER,
    TAG_DISCOUNT,
    TAG_ALIEXPRESS,
    TAG_SHOPEE,
)

_INTERNAL_CAMPAIGN_MARKERS = (
    "cpa",
    "aeb_",
    "es_products",
    "avasam",
    "selecteditems",
    "shipfrom",
    "_202",
)


def _is_displayable_campaign_name(name: str | None) -> bool:
    if not name or not name.strip():
        return False
    normalized = name.lower().replace(" ", "")
    return not any(marker in normalized for marker in _INTERNAL_CAMPAIGN_MARKERS)


def _format_brl(value: float | Decimal) -> str:
    formatted = f"{value:,.2f}"
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def _effective_price(promotion: Promotion) -> float | None:
    if promotion.final_price is not None:
        return promotion.final_price
    return promotion.price


def _build_link(promotion: Promotion) -> str:
    return promotion.affiliate_url or promotion.url


def _legacy_conditions_block(promotion: Promotion) -> list[str]:
    lines: list[str] = []

    if promotion.requires_pix or promotion.payment_method == "pix":
        lines.append("Pagamento via Pix")

    if promotion.price_conditions:
        lines.append("Condições:")
        for condition in promotion.price_conditions:
            lines.append(f"- {condition}")

    return lines


def _select_display_tags(promotion: Promotion) -> list[str]:
    ordered: list[str] = []

    if _is_displayable_campaign_name(promotion.campaign_name):
        ordered.append(promotion.campaign_name)

    present = set(promotion.promotion_tags)
    for tag in _TAG_PRIORITY:
        if tag in present:
            ordered.append(tag)

    unique_tags: list[str] = []
    for tag in ordered:
        if tag and tag not in unique_tags:
            unique_tags.append(tag)

    return unique_tags[:MAX_DISPLAY_TAGS]


def _has_price_range(promotion: Promotion) -> bool:
    metadata = promotion.metadata or {}
    return bool(metadata.get("has_price_range"))


def _build_price_lines(promotion: Promotion) -> list[str]:
    price = _effective_price(promotion)
    price_text = _format_brl(price) if price is not None else "Preço indisponível"
    old_price = promotion.old_price
    has_range = _has_price_range(promotion)

    if (
        old_price is not None
        and price is not None
        and old_price > price
    ):
        por_text = f"A partir de {price_text}" if has_range else price_text
        return [f"De: {_format_brl(old_price)}", f"Por: {por_text}"]

    if has_range:
        return [f"💰 A partir de {price_text}"]

    if promotion.source == SOURCE_SHOPEE:
        return [f"💰 {price_text}"]

    return [f"Preço: {price_text}"]


def _build_sku_group_lines(promotion: Promotion) -> list[str] | None:
    group = (promotion.metadata or {}).get("sku_offer_group")
    if not isinstance(group, dict):
        return None
    variations = [
        variation
        for variation in group.get("variations", [])
        if isinstance(variation, dict) and variation.get("price") is not None
    ]
    if not variations:
        return None
    variations.sort(key=lambda variation: Decimal(str(variation["price"])))
    unique_variations: dict[str, dict] = {}
    for variation in variations:
        label = str(variation.get("label") or "Padrão").strip()
        unique_variations.setdefault(label.lower(), variation)
    variations = list(unique_variations.values())

    prices = [Decimal(str(variation["price"])) for variation in variations]
    minimum_price = min(prices)
    maximum_price = max(prices)
    labels = [str(variation.get("label") or "Padrão") for variation in variations]
    meaningful_labels = [
        label
        for label in labels
        if label.strip().lower() not in _EMPTY_VARIATION_LABELS
    ]

    if len(variations) == 1:
        return _build_price_lines(promotion)

    if not meaningful_labels:
        return _build_price_lines(promotion)

    if minimum_price == maximum_price:
        return [
            f"💰 {_format_brl(minimum_price)}",
            f"🏷️ Variações: {', '.join(meaningful_labels)}",
        ]

    lines = [
        f"💰 A partir de {_format_brl(minimum_price)}",
        "",
        "🏷️ Variações:",
    ]
    for variation in variations:
        lines.append(
            f"• {variation.get('label') or 'Padrão'} — "
            f"{_format_brl(Decimal(str(variation['price'])))}"
        )
    return lines


def _build_sku_delivery_lines(promotion: Promotion) -> list[str]:
    metadata = promotion.metadata or {}
    if not metadata.get("display_sku_delivery"):
        return []
    group = metadata.get("sku_offer_group")
    if not isinstance(group, dict):
        return []
    variations = [
        variation
        for variation in group.get("variations", [])
        if isinstance(variation, dict)
    ]
    if not variations:
        return []

    delivery_signatures = {
        (
            variation.get("shipping_fee"),
            variation.get("min_delivery_days"),
            variation.get("max_delivery_days"),
            variation.get("delivery_days"),
        )
        for variation in variations
    }
    if len(delivery_signatures) > 1:
        return ["🚚 Frete e prazo variam conforme a opção escolhida"]

    representative = variations[0]
    shipping_fee = representative.get("shipping_fee")
    minimum_days = representative.get("min_delivery_days")
    maximum_days = representative.get("max_delivery_days")
    delivery_days = representative.get("delivery_days")
    lines: list[str] = []

    if shipping_fee is not None:
        fee = Decimal(str(shipping_fee))
        if fee == 0:
            lines.append("🚚 Frete grátis estimado para o Brasil")
        else:
            lines.append(
                f"🚚 Frete estimado para o Brasil: {_format_brl(fee)}"
            )

    if minimum_days is not None and maximum_days is not None:
        lines.append(
            f"📦 Entrega estimada: {minimum_days} a {maximum_days} dias"
        )
    elif delivery_days is not None:
        lines.append(f"📦 Entrega estimada: até {delivery_days} dias")
    return lines


def _build_coupon_section(promotion: Promotion, now: datetime) -> list[str]:
    if not promotion.coupons:
        return []

    displayed, has_more = select_display_coupons(
        promotion.coupons, now, max_coupons=MAX_PRODUCT_COUPONS
    )
    if not displayed:
        return []

    lines: list[str] = []
    for coupon in displayed:
        lines.extend(build_product_coupon_lines(coupon))
        lines.append("")

    if has_more:
        lines.append(MORE_COUPONS_TEXT)
    else:
        lines = lines[:-1]

    return lines


def _build_core_lines(promotion: Promotion, now: datetime) -> list[str]:
    store = promotion.store or "Loja parceira"

    lines: list[str] = []

    display_tags = _select_display_tags(promotion)
    if display_tags:
        lines.append(f"🏷️ {' • '.join(display_tags)}")

    if lines:
        lines.append("")
    lines.extend([promotion.title, ""])
    sku_group_lines = _build_sku_group_lines(promotion)
    lines.extend(sku_group_lines or _build_price_lines(promotion))

    coupon_section = _build_coupon_section(promotion, now)
    if coupon_section:
        lines.append("")
        lines.extend(coupon_section)

    legacy_conditions = _legacy_conditions_block(promotion)
    if legacy_conditions:
        lines.append("")
        lines.extend(legacy_conditions)

    delivery_lines = _build_sku_delivery_lines(promotion)
    if delivery_lines:
        lines.append("")
        lines.extend(delivery_lines)

    lines.extend(["", f"Loja: {store}"])
    return lines


def _aliexpress_disclaimer(promotion: Promotion) -> list[str]:
    if promotion.source == SOURCE_ALIEXPRESS:
        return [
            "",
            "Obs.: preço sujeito a alteração; confirme o valor no carrinho do AliExpress.",
        ]
    return []


def _coupon_action(promotion: Promotion, product_url: str | None, now: datetime) -> MessageAction | None:
    if not promotion.coupons:
        return None
    displayed, _ = select_display_coupons(
        promotion.coupons, now, max_coupons=MAX_PRODUCT_COUPONS
    )
    for coupon in displayed:
        coupon_url = coupon.affiliate_url or coupon.coupon_url
        if coupon_url and coupon_url != product_url:
            return MessageAction(
                text=COUPON_BUTTON_TEXT, url=coupon_url, action_type="coupon"
            )
    return None


def _build_actions(
    promotion: Promotion, product_url: str | None, now: datetime
) -> list[MessageAction]:
    actions: list[MessageAction] = []
    if product_url:
        text = PRODUCT_BUTTON_TEXT if promotion.coupons else DEFAULT_BUTTON_TEXT
        actions.append(
            MessageAction(text=text, url=product_url, action_type="product")
        )

    coupon_action = _coupon_action(promotion, product_url, now)
    if coupon_action is not None:
        actions.append(coupon_action)

    return actions


def format_promotion(promotion: Promotion, now: datetime | None = None) -> FormattedMessage:
    current = now or now_in_timezone()
    offer_url = _build_link(promotion) or None

    lines = _build_core_lines(promotion, current)

    if not offer_url:
        link = _build_link(promotion)
        if link:
            lines.extend(["", "Ver oferta:", link])

    lines.extend(_aliexpress_disclaimer(promotion))

    actions = _build_actions(promotion, offer_url, current)

    return FormattedMessage(
        text="\n".join(lines),
        image_url=promotion.image_url or None,
        actions=actions,
        offer_url=offer_url,
        button_text=DEFAULT_BUTTON_TEXT,
    )


def format_promotion_message(promotion: Promotion, now: datetime | None = None) -> str:
    current = now or now_in_timezone()
    lines = _build_core_lines(promotion, current)
    link = _build_link(promotion)
    if link:
        lines.extend(["", "Ver oferta:", link])
    lines.extend(_aliexpress_disclaimer(promotion))
    return "\n".join(lines)
