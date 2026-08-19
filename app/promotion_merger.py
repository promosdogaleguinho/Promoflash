from app.models import Promotion


def _group_key(promotion: Promotion) -> str:
    if promotion.external_id:
        return f"{promotion.source}:{promotion.external_id}"
    if promotion.product_key:
        return promotion.product_key
    return f"{promotion.source}:{id(promotion)}"


def _base_sort_key(promotion: Promotion) -> tuple:
    has_affiliate = 1 if promotion.affiliate_url else 0
    has_price = 1 if promotion.final_price is not None else 0
    price = promotion.final_price if promotion.final_price is not None else float("inf")
    has_image = 1 if promotion.image_url else 0
    is_official = 1 if promotion.is_official_campaign else 0
    metadata_size = len(promotion.metadata or {})
    score = promotion.promotion_score or 0.0

    return (
        -has_affiliate,
        -has_price,
        price,
        -has_image,
        -is_official,
        -metadata_size,
        -score,
    )


def _append_unique(target: list, values: list) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)


def _choose_main_campaign(group: list[Promotion]) -> str | None:
    official = [
        promotion.campaign_name
        for promotion in group
        if promotion.is_official_campaign and promotion.campaign_name
    ]
    if official:
        return official[0]
    named = [promotion.campaign_name for promotion in group if promotion.campaign_name]
    return named[0] if named else None


def _merge_group(group: list[Promotion]) -> Promotion:
    base = sorted(group, key=_base_sort_key)[0]

    promotion_tags = list(base.promotion_tags)
    generic_tags = list(base.tags)
    collector_types: list[str] = []
    campaign_names: list[str] = []
    best_score = base.promotion_score or 0.0
    has_official = False

    for promotion in group:
        _append_unique(promotion_tags, promotion.promotion_tags)
        _append_unique(generic_tags, promotion.tags)

        collector_type = (promotion.metadata or {}).get("collector_type")
        if collector_type:
            _append_unique(collector_types, [collector_type])

        if promotion.campaign_name:
            _append_unique(campaign_names, [promotion.campaign_name])

        if (promotion.promotion_score or 0.0) > best_score:
            best_score = promotion.promotion_score or 0.0

        if promotion.is_official_campaign:
            has_official = True

    base.promotion_tags = promotion_tags
    base.tags = generic_tags
    base.promotion_score = best_score

    if has_official:
        base.is_official_campaign = True
        main_campaign = _choose_main_campaign(group)
        if main_campaign:
            base.campaign_name = main_campaign

    base.metadata = dict(base.metadata or {})
    base.metadata["collector_types"] = collector_types
    base.metadata["campaign_names"] = campaign_names

    return base


def merge_duplicate_promotions(promotions: list[Promotion]) -> list[Promotion]:
    groups: dict[str, list[Promotion]] = {}
    order: list[str] = []

    for promotion in promotions:
        key = _group_key(promotion)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(promotion)

    merged: list[Promotion] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue
        merged.append(_merge_group(group))

    return merged
