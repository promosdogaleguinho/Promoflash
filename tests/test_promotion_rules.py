from app.models import Promotion
from app.promotion_quality import TAG_HIGH_INTENT
from app.promotion_rules import apply_promotion_rules

_BASE_RULES = {
    "global": {
        "min_promotion_score": 20,
        "min_price": 5,
        "max_price": 8000,
        "max_title_length": 190,
        "soft_discount_percentage": 10,
        "strong_discount_percentage": 20,
        "blocked_keywords": ["replica", "fake"],
        "high_intent_keywords": ["ps5", "iphone", "ssd"],
        "preferred_keywords": ["bluetooth", "gamer"],
        "trusted_brands": ["kingston", "machenike", "xiaomi"],
    },
    "sources": {},
    "categories": {},
}


def _promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "1",
        "source": "aliexpress",
        "title": "Produto Generico",
        "url": "https://example.com/p",
        "affiliate_url": "https://s.click.aliexpress.com/e/abc",
        "final_price": 100.0,
        "price": 100.0,
    }
    defaults.update(kwargs)
    return Promotion(**defaults)


def _rules(**global_overrides) -> dict:
    rules = {
        "global": dict(_BASE_RULES["global"]),
        "sources": {},
        "categories": {},
    }
    rules["global"].update(global_overrides)
    return rules


def test_approves_promotion_within_rules():
    promo = _promotion(
        title="SSD NVMe 1TB",
        discount_percentage=25.0,
        old_price=200.0,
        final_price=150.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is True
    assert reasons == []


def test_rejects_price_below_minimum():
    promo = _promotion(title="Produto barato", final_price=3.0)
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is False
    assert any("minimo" in reason for reason in reasons)


def test_rejects_price_above_maximum():
    promo = _promotion(title="Produto caro", final_price=9000.0)
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is False
    assert any("maximo" in reason for reason in reasons)


def test_blocked_keyword_rejects():
    promo = _promotion(title="Produto fake barato")
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_blocked_keyword_ignores_accent_and_case():
    promo = _promotion(title="RÉPLICA Perfeita do Relogio")
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is False
    assert any("blocked keyword" in reason for reason in reasons)


def test_source_rule_overrides_global():
    rules = _rules()
    rules["sources"] = {"aliexpress": {"max_price": 50}}
    promo = _promotion(title="Produto generico", final_price=100.0)

    approved, reasons = apply_promotion_rules(promo, rules)

    assert approved is False
    assert any("maximo" in reason for reason in reasons)


def test_category_rule_overrides_global():
    rules = _rules()
    rules["categories"] = {"games": {"max_price": 40}}
    promo = _promotion(
        title="Jogo generico",
        final_price=100.0,
        resolved_category="games",
    )

    approved, reasons = apply_promotion_rules(promo, rules)

    assert approved is False
    assert any("maximo" in reason for reason in reasons)


def test_preferred_keyword_increases_score():
    with_preferred = _promotion(title="Fone Bluetooth Comum")
    without_preferred = _promotion(title="Fone Comum XYZ")

    apply_promotion_rules(with_preferred, _rules())
    apply_promotion_rules(without_preferred, _rules())

    assert with_preferred.promotion_score > without_preferred.promotion_score


def test_high_intent_approves_low_discount_product():
    promo = _promotion(
        title="Console PS5 Edicao Digital",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is True
    assert reasons == []


def test_generic_product_rejected_when_relevance_required():
    promo = _promotion(
        title="Produto Generico Qualquer XYZ",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules(require_relevance=True))

    assert approved is False
    assert any("irrelevante" in reason for reason in reasons)


def test_preferred_alone_does_not_pass_relevance():
    promo = _promotion(
        title="Cabo Bluetooth Generico Sem Marca",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules(require_relevance=True))

    assert approved is False
    assert any("irrelevante" in reason for reason in reasons)


def test_trusted_brand_passes_with_small_discount():
    promo = _promotion(
        title="Controle Sem Fio Machenike G5 Pro V2",
        discount_percentage=2.0,
        old_price=102.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(
        promo, _rules(require_relevance=True, soft_discount_percentage=1)
    )

    assert approved is True
    assert reasons == []


def test_high_intent_small_discount_is_approved():
    promo = _promotion(
        title="SSD NVMe 1TB",
        discount_percentage=2.0,
        old_price=102.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(
        promo, _rules(require_relevance=True, soft_discount_percentage=1)
    )

    assert approved is True
    assert reasons == []


def test_social_proof_requires_sales_and_rating():
    promo = _promotion(
        title="Item Popular Sem Keyword Obvia",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
        sales=250,
        rating=4.8,
    )
    approved, reasons = apply_promotion_rules(
        promo,
        _rules(
            require_relevance=True,
            high_intent_keywords=[],
            trusted_brands=[],
            relevance_min_sales=100,
            relevance_min_rating=4.5,
        ),
    )

    assert approved is True
    assert reasons == []


def test_high_sales_without_rating_does_not_pass():
    promo = _promotion(
        title="Item Popular Sem Nota",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
        sales=250,
    )
    approved, reasons = apply_promotion_rules(
        promo,
        _rules(
            require_relevance=True,
            high_intent_keywords=[],
            trusted_brands=[],
            relevance_min_sales=100,
            relevance_min_rating=4.5,
        ),
    )

    assert approved is False
    assert any("irrelevante" in reason for reason in reasons)


def test_official_campaign_is_approved_without_relevance_gate():
    promo = _promotion(
        title="Produto Generico",
        is_official_campaign=True,
    )
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is True
    assert reasons == []


def test_official_campaign_alone_does_not_bypass_relevance():
    promo = _promotion(
        title="Produto Generico Sem Sinal",
        is_official_campaign=True,
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules(require_relevance=True))

    assert approved is False
    assert any("irrelevante" in reason for reason in reasons)


def test_returns_rejection_reasons_list():
    promo = _promotion(title="Produto fake caro", final_price=9000.0)
    approved, reasons = apply_promotion_rules(promo, _rules())

    assert approved is False
    assert isinstance(reasons, list)
    assert len(reasons) >= 1


def test_high_intent_adds_desired_product_tag():
    promo = _promotion(
        title="iPhone 15 Pro Max",
        discount_percentage=5.0,
        old_price=105.0,
        final_price=100.0,
    )
    approved, _ = apply_promotion_rules(promo, _rules())

    assert approved is True
    assert TAG_HIGH_INTENT in promo.promotion_tags


def test_shopee_source_also_uses_relevance_gate():
    promo = _promotion(
        source="shopee",
        title="Produto Generico Shopee",
        discount_percentage=10.0,
        old_price=110.0,
        final_price=100.0,
    )
    approved, reasons = apply_promotion_rules(promo, _rules(require_relevance=True))

    assert approved is False
    assert any("irrelevante" in reason for reason in reasons)
