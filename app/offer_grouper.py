from app.models import Promotion
from app.product_identity import build_product_key


def group_by_product(promotions: list[Promotion]) -> dict[str, list[Promotion]]:
    groups: dict[str, list[Promotion]] = {}

    for promotion in promotions:
        product_key = build_product_key(promotion)
        groups.setdefault(product_key, []).append(promotion)

    return groups
