import logging

logger = logging.getLogger(__name__)

CATEGORY_CHANNEL_ALIASES = {
    "moveis": "casa",
    "roupas": "moda",
}

COUPONS_DESTINATION = "cupons"


def _destination_for_category(
    category: str,
    channel_name: str,
    channel_data: dict,
    *,
    allow_geral_fallback: bool = True,
) -> dict | None:
    channel_destinations = channel_data.get("destinations", {})
    lookup_category = CATEGORY_CHANNEL_ALIASES.get(category, category)
    destination = channel_destinations.get(lookup_category)
    resolved_category = lookup_category

    if destination is None or not destination.get("enabled", True):
        if not allow_geral_fallback:
            return None
        destination = channel_destinations.get("geral")
        resolved_category = "geral"

    if destination is None or not destination.get("enabled", True):
        return None

    chat_id = destination.get("chat_id")
    if not chat_id:
        return None

    return {
        "channel": channel_name,
        "chat_id": chat_id,
        "category": resolved_category,
    }


def route_promotion(category: str, channels_config: dict) -> list[dict]:
    destinations: list[dict] = []

    for channel_name, channel_data in channels_config.items():
        if not channel_data.get("enabled", False):
            continue

        destination = _destination_for_category(
            category,
            channel_name,
            channel_data,
            allow_geral_fallback=True,
        )
        if destination is None:
            continue
        destinations.append(destination)

    if not destinations:
        logger.warning("Nenhum destino encontrado para categoria: %s", category)

    return destinations


def route_campaign_offer(
    kind: str,
    category: str,
    channels_config: dict,
) -> list[dict]:
    """Roteia ofertas Awin (e futuras fontes de campanha).

    voucher → sempre cupons + categoria temática (ou geral)
    promotion → apenas categoria temática (ou geral); nunca cupons
    """
    resolved_category = CATEGORY_CHANNEL_ALIASES.get(category, category) or "geral"
    destinations: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for channel_name, channel_data in channels_config.items():
        if not channel_data.get("enabled", False):
            continue

        channel_destinations = channel_data.get("destinations", {})

        if kind == "voucher":
            coupons = channel_destinations.get(COUPONS_DESTINATION)
            if coupons and coupons.get("enabled", True) and coupons.get("chat_id"):
                key = (channel_name, COUPONS_DESTINATION)
                if key not in seen:
                    destinations.append(
                        {
                            "channel": channel_name,
                            "chat_id": coupons["chat_id"],
                            "category": COUPONS_DESTINATION,
                        }
                    )
                    seen.add(key)

            thematic = _destination_for_category(
                resolved_category,
                channel_name,
                channel_data,
                allow_geral_fallback=True,
            )
            if thematic is not None:
                key = (thematic["channel"], thematic["category"])
                if key not in seen:
                    destinations.append(thematic)
                    seen.add(key)
            continue

        thematic = _destination_for_category(
            resolved_category,
            channel_name,
            channel_data,
            allow_geral_fallback=True,
        )
        if thematic is None:
            continue
        if thematic["category"] == COUPONS_DESTINATION:
            continue
        key = (thematic["channel"], thematic["category"])
        if key not in seen:
            destinations.append(thematic)
            seen.add(key)

    if not destinations:
        logger.warning(
            "Nenhum destino encontrado para oferta kind=%s category=%s",
            kind,
            category,
        )

    return destinations
