import copy
from datetime import datetime

from app.coupon_lifecycle import get_timezone
from app.coupon_pipeline import (
    attach_api_product_coupons,
    attach_product_coupons,
    extract_product_coupons_from_api,
)
from app.models import Coupon, CouponScopeType, Promotion

TZ = get_timezone("America/Sao_Paulo")
NOW = datetime(2030, 1, 12, 12, 0, tzinfo=TZ)


def _promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "P1",
        "source": "aliexpress",
        "title": "Produto",
        "url": "https://example.com",
    }
    defaults.update(kwargs)
    return Promotion(**defaults)


def test_missing_raw_does_not_break_promotion():
    promotion = _promotion(metadata={"collector_type": "product_search"})
    attached = attach_api_product_coupons(promotion, NOW)
    assert attached == 0
    assert promotion.coupons == []


def test_invalid_raw_type_is_ignored():
    promotion = _promotion(metadata={"raw": "not-a-dict"})
    assert extract_product_coupons_from_api(promotion) == []
    assert attach_api_product_coupons(promotion, NOW) == 0


def test_raw_without_coupons_does_not_break():
    raw = {"product_id": "P1", "product_title": "X", "sale_price": "10"}
    promotion = _promotion(metadata={"raw": raw})
    attached = attach_api_product_coupons(promotion, NOW)
    assert attached == 0
    assert promotion.coupons == []


def test_extracts_and_attaches_coupons_to_normalized_model():
    raw = {"coupon_info": {"coupon_code": "PDF01", "discount_value": "12", "minimum_spend": "90"}}
    promotion = _promotion(metadata={"raw": raw})
    attached = attach_api_product_coupons(promotion, NOW)
    assert attached == 1
    assert promotion.coupons[0].code == "PDF01"
    assert promotion.coupons[0].scope_type == CouponScopeType.PRODUCT
    assert promotion.coupons[0].scope_value == "P1"


def test_raw_payload_is_not_modified():
    raw = {"coupon_info": {"coupon_code": "PDF01", "discount_value": "12"}}
    snapshot = copy.deepcopy(raw)
    promotion = _promotion(metadata={"raw": raw})
    attach_api_product_coupons(promotion, NOW)
    assert raw == snapshot


def test_unknown_source_skips_api_extraction():
    promotion = Promotion(
        external_id="P1",
        source="shopee",
        title="Produto",
        url="https://example.com",
        metadata={"raw": {"coupon_code": "SHOP10"}},
    )
    assert extract_product_coupons_from_api(promotion) == []


def test_manual_binding_works_without_raw():
    coupon = Coupon(
        source="shopee",
        code="MANUAL",
        scope_type=CouponScopeType.PRODUCT,
        scope_value="SP1",
        metadata={"attachment_reason": "manual_product_binding"},
    )
    promotion = Promotion(
        external_id="SP1",
        source="shopee",
        title="Produto",
        url="https://example.com",
    )
    bindings = {("shopee", "SP1"): [coupon]}
    products_with_coupons, attached = attach_product_coupons([promotion], bindings, NOW)
    assert attached == 1
    assert products_with_coupons == 1
    assert promotion.coupons[0].code == "MANUAL"


def test_batch_continues_when_extraction_fails(monkeypatch):
    good = _promotion(
        external_id="GOOD",
        metadata={"raw": {"coupon_info": {"coupon_code": "OK", "discount_value": "5"}}},
    )
    bad = _promotion(external_id="BAD", metadata={"raw": {"coupon_info": {}}})

    from app.collectors.aliexpress_coupon_extractor import extract_aliexpress_coupons

    original = extract_aliexpress_coupons

    def _safe_extract(item, campaign=None):
        if item is bad.metadata["raw"]:
            raise RuntimeError("simulated failure")
        return original(item, campaign)

    monkeypatch.setattr(
        "app.coupon_pipeline.extract_aliexpress_coupons",
        _safe_extract,
    )

    products_with_coupons, attached = attach_product_coupons([good, bad], {}, NOW)
    assert attached == 1
    assert products_with_coupons == 1
    assert good.coupons[0].code == "OK"
    assert bad.coupons == []
