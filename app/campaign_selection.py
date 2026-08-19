import logging
import unicodedata

logger = logging.getLogger(__name__)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    return " ".join(without_accents.replace("-", " ").replace("_", " ").split())


def _campaign_name(campaign: dict) -> str | None:
    name = campaign.get("promotion_name") or campaign.get("promotion_id")
    if not name:
        return None
    return str(name)


def _is_blocked(name: str, blocked: list) -> bool:
    normalized = _normalize(name)
    return any(_normalize(item) == normalized for item in blocked)


def _matches_allowed(name: str, allowed: list) -> bool:
    if not allowed:
        return True
    normalized = _normalize(name)
    return any(_normalize(item) == normalized for item in allowed)


def _preference_rank(name: str, preferred_patterns: list[str]) -> int | None:
    normalized = _normalize(name)
    for index, pattern in enumerate(preferred_patterns):
        if _normalize(pattern) in normalized:
            return index
    return None


def _product_count(campaign: dict) -> int:
    raw = campaign.get("raw")
    if not isinstance(raw, dict):
        return 0
    value = raw.get("product_num")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _matches_blocked_pattern(name: str, blocked_patterns: list[str]) -> bool:
    normalized = _normalize(name)
    for pattern in blocked_patterns:
        if _normalize(pattern) in normalized:
            return True
    return False


def select_featured_campaigns(
    campaigns: list[dict],
    max_campaigns: int,
    allowed_campaigns: list | None = None,
    blocked_campaigns: list | None = None,
    preferred_patterns: list | None = None,
    blocked_patterns: list | None = None,
) -> list[dict]:
    """Seleciona campanhas com filtro, preferência e fallback.

    Ordem quando `allowed_campaigns` está vazio:
    1. campanhas que batem com `preferred_patterns` (na ordem do padrão)
    2. demais campanhas, priorizando maior `product_num`
    """
    allowed = allowed_campaigns or []
    blocked = blocked_campaigns or []
    preferred = preferred_patterns or []
    blocked_by_pattern = blocked_patterns or []

    eligible: list[dict] = []
    for campaign in campaigns:
        name = _campaign_name(campaign)
        if not name:
            continue
        if _is_blocked(name, blocked):
            continue
        if _matches_blocked_pattern(name, blocked_by_pattern):
            continue
        if not _matches_allowed(name, allowed):
            continue
        eligible.append(campaign)

    if not eligible and allowed and campaigns:
        sample = [
            _campaign_name(campaign)
            for campaign in campaigns[:10]
            if _campaign_name(campaign)
        ]
        logger.warning(
            "Nenhuma campanha bateu com allowed_campaigns=%s. "
            "Usando preferência/fallback. Amostra: %s",
            allowed,
            sample,
        )
        for campaign in campaigns:
            name = _campaign_name(campaign)
            if not name:
                continue
            if _is_blocked(name, blocked):
                continue
            if _matches_blocked_pattern(name, blocked_by_pattern):
                continue
            eligible.append(campaign)

    if not eligible:
        return []

    def sort_key(campaign: dict) -> tuple:
        name = _campaign_name(campaign) or ""
        rank = _preference_rank(name, preferred)
        preferred_bucket = 0 if rank is not None else 1
        preference_index = rank if rank is not None else 999
        return (preferred_bucket, preference_index, -_product_count(campaign))

    ordered = sorted(eligible, key=sort_key)
    selected = ordered[:max_campaigns]
    logger.info(
        "Campanhas selecionadas: %s",
        [ _campaign_name(item) for item in selected ],
    )
    return selected
