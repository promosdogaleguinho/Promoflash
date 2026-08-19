import logging
import math
import re
import unicodedata
from dataclasses import dataclass

from app.models import CampaignOffer, Promotion

logger = logging.getLogger(__name__)

_TITLE_FIELD_WEIGHT = 3.0
_AUX_FIELD_WEIGHT = 1.0
_MIN_SCORE = 1.5
_CLOSE_SCORE_RATIO = 1.25
_DEFAULT_CATEGORY = "geral"

_WEAK_TERM_WEIGHT = 0.2
_WEAK_ALIASES = {
    "decoracao",
    "decoração",
    "presente",
    "aniversario",
    "aniversário",
    "mesa",
    "usb",
    "led",
    "inteligente",
    "cabo",
    "fonte",
    "cooler",
    "ventilador",
    "bola",
    "jogo",
    "mochila",
    "bolsa",
    "bota",
    "capa",
    "suporte",
    "case",
}


@dataclass(frozen=True)
class _MatchCandidate:
    contribution: float
    alias_length: int
    field: str
    start: int
    end: int
    alias: str


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    return without_accents.lower().strip()


def _match_alias(text: str, alias: str) -> bool:
    return _find_alias_span(text, alias) is not None


def _is_model_code_embedding(text: str, start: int, end: int) -> bool:
    if (
        end < len(text)
        and text[end] == "-"
        and end + 1 < len(text)
        and text[end + 1].isdigit()
    ):
        return True
    if (
        start >= 2
        and text[start - 1] == "-"
        and text[start - 2].isdigit()
    ):
        return True
    return False


def _find_alias_span(text: str, alias: str) -> tuple[int, int] | None:
    normalized_text = _normalize_text(text)
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return None
    if normalized_text == normalized_alias:
        return (0, len(normalized_text))
    pattern = (
        rf"(^|[^a-z0-9])({re.escape(normalized_alias)}s?)([^a-z0-9]|$)"
    )
    for match in re.finditer(pattern, normalized_text):
        start, end = match.start(2), match.end(2)
        if _is_model_code_embedding(normalized_text, start, end):
            continue
        return start, end
    return None


def _matches_any_keyword(text: str, keywords: list[str]) -> bool:
    for keyword in keywords:
        if _match_alias(text, keyword):
            return True
    return False


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _negative_terms(category_data: dict) -> list[str]:
    excludes = list(category_data.get("exclude_keywords", []))
    excludes.extend(category_data.get("negative_terms", []))
    return excludes


def _term_weight(term: str, category_data: dict) -> float:
    weights = category_data.get("term_weights", {})
    if term in weights:
        return float(weights[term])

    term_norm = _normalize_text(term)
    for key, value in weights.items():
        if _normalize_text(key) == term_norm:
            return float(value)

    boost_terms = category_data.get("boost_terms", {})
    if term in boost_terms:
        return float(boost_terms[term])
    for key, value in boost_terms.items():
        if _normalize_text(key) == term_norm:
            return float(value)

    if term_norm in _WEAK_ALIASES or term in _WEAK_ALIASES:
        return _WEAK_TERM_WEIGHT

    length = len(term_norm)
    return 1.0 + (length / 6.0)


def _idf(df: int, total_categories: int) -> float:
    if total_categories <= 0 or df <= 0:
        return 1.0
    return math.log(1.0 + ((total_categories - df + 0.5) / (df + 0.5)))


def _build_term_df(categories_config: dict) -> dict[str, int]:
    df: dict[str, int] = {}
    for category_key, category_data in categories_config.items():
        if category_key == _DEFAULT_CATEGORY:
            continue
        seen: set[str] = set()
        for alias in category_data.get("external_aliases", []):
            alias_norm = _normalize_text(alias)
            if not alias_norm or alias_norm in seen:
                continue
            seen.add(alias_norm)
            df[alias_norm] = df.get(alias_norm, 0) + 1
    return df


def _collect_match_candidates(
    category_data: dict,
    *,
    title: str,
    aux_text: str,
    term_df: dict[str, int],
    total_categories: int,
) -> list[_MatchCandidate]:
    candidates: list[_MatchCandidate] = []
    for alias in category_data.get("external_aliases", []):
        field = ""
        span: tuple[int, int] | None = None
        field_weight = 0.0

        if title:
            span = _find_alias_span(title, alias)
            if span is not None:
                field = "title"
                field_weight = _TITLE_FIELD_WEIGHT

        if span is None and aux_text:
            span = _find_alias_span(aux_text, alias)
            if span is not None:
                field = "aux"
                field_weight = _AUX_FIELD_WEIGHT

        if span is None:
            continue

        alias_norm = _normalize_text(alias)
        weight = _term_weight(alias, category_data)
        idf = _idf(term_df.get(alias_norm, 1), total_categories)
        contribution = weight * idf * field_weight
        candidates.append(
            _MatchCandidate(
                contribution=contribution,
                alias_length=len(alias_norm),
                field=field,
                start=span[0],
                end=span[1],
                alias=alias,
            )
        )
    return candidates


def _select_non_overlapping(
    candidates: list[_MatchCandidate],
) -> list[_MatchCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (item.contribution, item.alias_length),
        reverse=True,
    )
    accepted: list[_MatchCandidate] = []
    occupied: dict[str, list[tuple[int, int]]] = {"title": [], "aux": []}

    for candidate in ordered:
        field_spans = occupied[candidate.field]
        span = (candidate.start, candidate.end)
        if any(_spans_overlap(span, taken) for taken in field_spans):
            continue
        field_spans.append(span)
        accepted.append(candidate)

    return accepted


def _score_category(
    category_data: dict,
    *,
    title: str,
    aux_text: str,
    full_text: str,
    term_df: dict[str, int],
    total_categories: int,
) -> float:
    negatives = _negative_terms(category_data)
    if negatives and _matches_any_keyword(full_text, negatives):
        return 0.0

    candidates = _collect_match_candidates(
        category_data,
        title=title,
        aux_text=aux_text,
        term_df=term_df,
        total_categories=total_categories,
    )
    accepted = _select_non_overlapping(candidates)
    return sum(item.contribution for item in accepted)


def _rank_categories(
    title: str,
    aux_candidates: list[str],
    categories_config: dict,
) -> list[tuple[str, float]]:
    aux_text = " ".join(candidate for candidate in aux_candidates if candidate)
    full_text = " ".join(part for part in [title, aux_text] if part)
    if not full_text.strip():
        return []

    term_df = _build_term_df(categories_config)
    scorable = [
        key for key in categories_config.keys() if key != _DEFAULT_CATEGORY
    ]
    total_categories = len(scorable) or 1

    ranked: list[tuple[str, float]] = []
    for category_key in scorable:
        category_data = categories_config[category_key]
        score = _score_category(
            category_data,
            title=title or "",
            aux_text=aux_text,
            full_text=full_text,
            term_df=term_df,
            total_categories=total_categories,
        )
        if score > 0:
            ranked.append((category_key, score))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _is_close_race(ranked: list[tuple[str, float]]) -> bool:
    if len(ranked) < 2:
        return False
    best_score = ranked[0][1]
    second = ranked[1][1]
    if second <= 0 or best_score <= 0:
        return False
    return best_score / second <= _CLOSE_SCORE_RATIO


def _log_top_scores(ranked: list[tuple[str, float]], chosen: str) -> None:
    top3 = ranked[:3]
    payload = [(key, round(score, 3)) for key, score in top3]
    if _is_close_race(ranked):
        logger.info(
            "category_resolver top3=%s chosen=%s",
            payload,
            chosen,
        )
    else:
        logger.debug(
            "category_resolver top3=%s chosen=%s",
            payload,
            chosen,
        )


def resolve_category_from_candidates(
    candidates: list[str],
    categories_config: dict,
    *,
    title: str | None = None,
) -> str:
    title_text = title or ""
    aux_candidates = [
        candidate
        for candidate in candidates
        if candidate and candidate != title_text
    ]
    ranked = _rank_categories(title_text, aux_candidates, categories_config)

    if not ranked or ranked[0][1] < _MIN_SCORE:
        chosen = _DEFAULT_CATEGORY
        if ranked:
            _log_top_scores(ranked, chosen)
        return chosen

    chosen = ranked[0][0]
    _log_top_scores(ranked, chosen)
    return chosen


def resolve_category(promotion: Promotion, categories_config: dict) -> str:
    candidates: list[str] = []

    if promotion.category:
        candidates.append(promotion.category)

    candidates.extend(promotion.tags)

    if promotion.title:
        candidates.append(promotion.title)

    for value in promotion.metadata.values():
        if isinstance(value, str):
            candidates.append(value)

    matched = resolve_category_from_candidates(
        candidates,
        categories_config,
        title=promotion.title,
    )
    promotion.resolved_category = matched
    return matched


def resolve_campaign_offer_category(
    offer: CampaignOffer,
    categories_config: dict,
) -> str:
    candidates: list[str] = []
    if offer.category:
        candidates.append(offer.category)
    candidates.extend(offer.tags)
    if offer.title:
        candidates.append(offer.title)
    if offer.description:
        candidates.append(offer.description)
    for value in offer.metadata.values():
        if isinstance(value, str):
            candidates.append(value)

    matched = resolve_category_from_candidates(
        candidates,
        categories_config,
        title=offer.title,
    )
    offer.resolved_category = matched
    return matched
