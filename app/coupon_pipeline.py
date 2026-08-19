import logging
from collections.abc import Callable
from datetime import datetime

from app.clients.aliexpress import AliExpressClient
from app.collectors.aliexpress_coupon_extractor import extract_aliexpress_coupons
from app.coupon_matcher import attach_coupons_to_promotion
from app.models import Coupon, CouponScopeType, Promotion

logger = logging.getLogger(__name__)

SOURCE_ALIEXPRESS = "aliexpress"
DEFAULT_MAX_PRODUCT_DETAILS = 5

# Ponto único de leitura do payload bruto. O restante do sistema deve usar
# promotion.coupons e os campos normalizados, não metadata["raw"].
_RAW_METADATA_KEY = "raw"


def _extract_raw_payload(promotion: Promotion) -> dict | None:
    raw = (promotion.metadata or {}).get(_RAW_METADATA_KEY)
    if not isinstance(raw, dict):
        return None
    return raw


def _bind_as_product_coupon(coupon: Coupon, promotion: Promotion) -> None:
    coupon.scope_type = CouponScopeType.PRODUCT
    coupon.scope_value = promotion.external_id
    coupon.metadata["attachment_reason"] = "api_product_response"
    collector_type = (promotion.metadata or {}).get("collector_type")
    if collector_type:
        coupon.metadata["source_collector"] = f"aliexpress_{collector_type}"


def _attach(promotion: Promotion, coupons: list[Coupon], now: datetime) -> int:
    before = len(promotion.coupons)
    attach_coupons_to_promotion(promotion, coupons, now)
    return len(promotion.coupons) - before


def _extract_aliexpress_coupons(promotion: Promotion) -> list[Coupon]:
    raw = _extract_raw_payload(promotion)
    if raw is None:
        return []

    try:
        coupons = extract_aliexpress_coupons(raw)
    except Exception as exc:
        logger.warning(
            "Falha ao extrair cupons AliExpress (source=%s external_id=%s): %s",
            promotion.source,
            promotion.external_id,
            exc,
        )
        return []

    for coupon in coupons:
        _bind_as_product_coupon(coupon, promotion)
    return coupons


_SOURCE_EXTRACTORS: dict[str, Callable[[Promotion], list[Coupon]]] = {
    SOURCE_ALIEXPRESS: _extract_aliexpress_coupons,
}


def extract_product_coupons_from_api(promotion: Promotion) -> list[Coupon]:
    extractor = _SOURCE_EXTRACTORS.get(promotion.source)
    if extractor is None:
        return []
    return extractor(promotion)


def attach_api_product_coupons(promotion: Promotion, now: datetime) -> int:
    coupons = extract_product_coupons_from_api(promotion)
    if not coupons:
        return 0
    return _attach(promotion, coupons, now)


def attach_manual_product_coupons(
    promotion: Promotion,
    bindings: dict[tuple[str, str], list[Coupon]],
    now: datetime,
) -> int:
    coupons = bindings.get((promotion.source, str(promotion.external_id)), [])
    if not coupons:
        return 0
    return _attach(promotion, coupons, now)


def enrich_aliexpress_coupons_from_product_detail(
    promotions: list[Promotion],
    client: AliExpressClient | None,
    now: datetime,
    max_details: int = DEFAULT_MAX_PRODUCT_DETAILS,
) -> int:
    """Consulta productdetail.get em amostra de produtos sem cupom já anexado.

    Não inventa cupons: só anexa o que a API oficial devolver em promo_code_info.
    """
    if client is None or max_details <= 0:
        return 0

    eligible = [
        promotion
        for promotion in promotions
        if promotion.source == SOURCE_ALIEXPRESS
        and promotion.external_id
        and not promotion.coupons
    ]
    product_ids: list[str] = []
    for promotion in eligible:
        product_id = str(
            (promotion.metadata or {}).get("parent_product_id")
            or promotion.external_id
        )
        if product_id not in product_ids:
            product_ids.append(product_id)
        if len(product_ids) >= max_details:
            break
    candidates = [
        promotion
        for promotion in eligible
        if str(
            (promotion.metadata or {}).get("parent_product_id")
            or promotion.external_id
        )
        in product_ids
    ]

    if not candidates:
        return 0

    try:
        details = client.product_detail_get(product_ids)
    except Exception as exc:
        logger.warning("Falha não bloqueante em productdetail.get (pipeline): %s", exc)
        return 0

    details_by_id = {
        str(item.get("product_id")): item
        for item in details
        if isinstance(item, dict) and item.get("product_id") is not None
    }

    attached_total = 0
    for promotion in candidates:
        product_id = str(
            (promotion.metadata or {}).get("parent_product_id")
            or promotion.external_id
        )
        detail = details_by_id.get(product_id)
        if not isinstance(detail, dict):
            continue
        try:
            coupons = extract_aliexpress_coupons(detail)
        except Exception as exc:
            logger.warning(
                "Falha ao extrair cupons de productdetail (external_id=%s): %s",
                promotion.external_id,
                exc,
            )
            continue
        for coupon in coupons:
            _bind_as_product_coupon(coupon, promotion)
            coupon.metadata["source_collector"] = "aliexpress_productdetail"
        attached_total += _attach(promotion, coupons, now)

    logger.info(
        "Product detail coupon enrichment: queried=%s attached=%s",
        len(product_ids),
        attached_total,
    )
    return attached_total


def attach_product_coupons(
    promotions: list[Promotion],
    bindings: dict[tuple[str, str], list[Coupon]],
    now: datetime,
    aliexpress_client: AliExpressClient | None = None,
    max_product_details: int = DEFAULT_MAX_PRODUCT_DETAILS,
) -> tuple[int, int]:
    products_with_coupons = 0
    coupons_attached = 0

    for promotion in promotions:
        try:
            attached = attach_api_product_coupons(promotion, now)
            attached += attach_manual_product_coupons(promotion, bindings, now)
        except Exception as exc:
            logger.warning(
                "Falha ao anexar cupons ao produto (source=%s external_id=%s): %s",
                promotion.source,
                promotion.external_id,
                exc,
            )
            attached = 0

        coupons_attached += attached

    coupons_attached += enrich_aliexpress_coupons_from_product_detail(
        promotions,
        aliexpress_client,
        now,
        max_details=max_product_details,
    )

    for promotion in promotions:
        if promotion.coupons:
            products_with_coupons += 1

    return products_with_coupons, coupons_attached
