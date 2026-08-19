import re
import unicodedata

MAX_DISPLAY_LENGTH = 40

DISPLAY_HOT_PRODUCT = "Produto em alta"
DISPLAY_NEW_ARRIVAL = "Novidade"
DISPLAY_BEST_SELLER = "Mais vendido"
DISPLAY_WEEKLY_DEALS = "Oferta da semana"
DISPLAY_ALIEXPRESS_CAMPAIGN = "Campanha AliExpress"

_CAMPAIGN_DISPLAY_NAMES = {
    "hot product": DISPLAY_HOT_PRODUCT,
    "hotproduct": DISPLAY_HOT_PRODUCT,
    "new arrival": DISPLAY_NEW_ARRIVAL,
    "newarrival": DISPLAY_NEW_ARRIVAL,
    "best seller": DISPLAY_BEST_SELLER,
    "bestseller": DISPLAY_BEST_SELLER,
    "weekly deals": DISPLAY_WEEKLY_DEALS,
    "weeklydeals": DISPLAY_WEEKLY_DEALS,
}
_ALIEXPRESS_INTERNAL_DISPLAY_NAMES = {
    "shipfrombr": "Envio do Brasil",
    "dropiselecteditems": "Itens selecionados",
}


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalize_key(campaign_name: str) -> str:
    without_accents = _strip_accents(campaign_name.lower())
    unified = re.sub(r"[_\-]+", " ", without_accents)
    return re.sub(r"\s+", " ", unified).strip()


def _sanitize(campaign_name: str) -> str:
    cleaned = re.sub(r"\s+", " ", campaign_name).strip()
    if len(cleaned) > MAX_DISPLAY_LENGTH:
        cleaned = cleaned[:MAX_DISPLAY_LENGTH].strip()
    return cleaned


def _aliexpress_internal_display_name(key: str) -> str | None:
    collapsed = key.replace(" ", "")
    if not collapsed.startswith("aebbr"):
        return None
    for internal_name, display_name in _ALIEXPRESS_INTERNAL_DISPLAY_NAMES.items():
        if internal_name in collapsed:
            return display_name
    return DISPLAY_ALIEXPRESS_CAMPAIGN


def get_campaign_display_name(campaign_name: str) -> str:
    if not campaign_name or not campaign_name.strip():
        return ""

    key = _normalize_key(campaign_name)
    internal_display_name = _aliexpress_internal_display_name(key)
    if internal_display_name:
        return internal_display_name
    if key in _CAMPAIGN_DISPLAY_NAMES:
        return _CAMPAIGN_DISPLAY_NAMES[key]

    collapsed = key.replace(" ", "")
    if collapsed in _CAMPAIGN_DISPLAY_NAMES:
        return _CAMPAIGN_DISPLAY_NAMES[collapsed]

    sanitized = _sanitize(campaign_name)
    return sanitized or campaign_name.strip()
