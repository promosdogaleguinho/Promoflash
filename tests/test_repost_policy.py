from datetime import datetime, timedelta, timezone

from app.models import Promotion, SentPromotionSnapshot
from app.product_identity import build_offer_key, build_product_key, build_product_price_key
from app.repost_policy import build_sent_snapshot, should_send_promotion


def _promotion(**kwargs) -> Promotion:
    defaults = {
        "external_id": "1",
        "source": "mock",
        "title": "Headphone JBL",
        "url": "https://example.com",
        "canonical_product_id": "jbl-tune-510bt",
        "final_price": 199.90,
        "price": 199.90,
    }
    defaults.update(kwargs)
    promotion = Promotion(**defaults)
    build_product_key(promotion)
    build_offer_key(promotion)
    build_product_price_key(promotion)
    return promotion


def _snapshot_from_promotion(promotion: Promotion, hours_ago: int = 1) -> SentPromotionSnapshot:
    snapshot = build_sent_snapshot(promotion)
    sent_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    snapshot.sent_at = sent_time.isoformat()
    return snapshot


def test_same_offer_recently_not_sent():
    promotion = _promotion(external_id="offer-1")
    snapshot = _snapshot_from_promotion(promotion)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_same_product_same_price_recently_not_sent():
    promotion = _promotion(external_id="offer-2", seller_id="seller-b")
    base = _promotion(external_id="offer-1", seller_id="seller-a")
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_same_product_lower_price_allowed():
    promotion = _promotion(external_id="offer-2", final_price=179.90, price=179.90)
    build_product_price_key(promotion)
    base = _promotion(external_id="offer-1", final_price=199.90, price=199.90)
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is True


def test_same_product_tiny_price_drop_not_allowed():
    """Oscilacao de centavos da API nao deve republicar na janela."""
    promotion = _promotion(external_id="offer-2", final_price=198.90, price=198.90)
    build_product_price_key(promotion)
    base = _promotion(external_id="offer-1", final_price=199.90, price=199.90)
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_same_product_new_free_shipping_blocked_when_title_and_price_equal():
    promotion = _promotion(
        external_id="offer-2",
        free_shipping=True,
        is_official_store=False,
    )
    base = _promotion(external_id="offer-1", free_shipping=False)
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_same_product_new_official_store_blocked_when_title_and_price_equal():
    promotion = _promotion(
        external_id="offer-2",
        is_official_store=True,
        free_shipping=False,
    )
    base = _promotion(external_id="offer-1", is_official_store=False, free_shipping=False)
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_same_product_new_coupon_blocked_when_title_and_price_equal():
    promotion = _promotion(
        external_id="offer-2",
        coupon_code="NOVO10",
        is_official_store=False,
        free_shipping=False,
    )
    build_product_price_key(promotion)
    base = _promotion(
        external_id="offer-1",
        is_official_store=False,
        free_shipping=False,
    )
    snapshot = _snapshot_from_promotion(base)
    assert should_send_promotion(promotion, [snapshot], 6) is False


def test_different_ids_same_title_same_price_blocked():
    first = _promotion(
        external_id="1453485282:58254983738",
        canonical_product_id=None,
        title="Caixa Organizadora MDF Com Tampa Rosa Porta Lacos",
        final_price=17.60,
        price=17.60,
    )
    second = _promotion(
        external_id="1453485282:23499339635",
        canonical_product_id=None,
        title="Caixa Organizadora MDF Com Tampa Rosa Porta Lacos",
        final_price=17.60,
        price=17.60,
    )
    snapshot = _snapshot_from_promotion(first)
    assert should_send_promotion(second, [snapshot], 24) is False


def test_near_duplicate_titles_same_price_blocked():
    first = _promotion(
        external_id="a",
        canonical_product_id=None,
        title=(
            "Caixa Organizadora MDF Com Tampa Rosa Porta Lacos Infantil "
            "Decorativa Sapato Grande Organizador De Acessorios"
        ),
        final_price=17.60,
        price=17.60,
    )
    second = _promotion(
        external_id="b",
        canonical_product_id=None,
        title=(
            "Caixa Organizadora MDF Rosa Com Tampa Porta Lacos Infantil "
            "Decorativa Grande Organizador De Acessorios Menina Sapato"
        ),
        final_price=19.37,
        price=19.37,
    )
    snapshot = _snapshot_from_promotion(first)
    assert should_send_promotion(second, [snapshot], 24) is False

    same_price = _promotion(
        external_id="c",
        canonical_product_id=None,
        title=(
            "Caixa Organizadora MDF Rosa Com Tampa Porta Lacos Infantil "
            "Decorativa Grande Organizador De Acessorios Menina Sapato"
        ),
        final_price=17.60,
        price=17.60,
    )
    assert should_send_promotion(same_price, [snapshot], 24) is False


def test_same_title_lower_price_allowed():
    first = _promotion(
        external_id="a",
        canonical_product_id=None,
        title="Mesa Gamer Escrivaninha Para Computador",
        final_price=298.72,
        price=298.72,
    )
    cheaper = _promotion(
        external_id="b",
        canonical_product_id=None,
        title="Mesa Gamer Escrivaninha Para Computador",
        final_price=250.00,
        price=250.00,
    )
    snapshot = _snapshot_from_promotion(first)
    assert should_send_promotion(cheaper, [snapshot], 24) is True


def test_outside_window_can_send_again():
    promotion = _promotion(external_id="offer-1")
    snapshot = _snapshot_from_promotion(promotion, hours_ago=7)
    assert should_send_promotion(promotion, [snapshot], 6) is True


def test_new_sku_group_from_same_parent_blocked_unless_cheaper():
    def sku_offer(group: str, sku_id: str, price: float = 100) -> Promotion:
        return _promotion(
            external_id=f"p1:{group}",
            source="aliexpress",
            canonical_product_id="p1",
            price=price,
            final_price=price,
            metadata={
                "parent_product_id": "p1",
                "sku_offer_group": {
                    "product_id": "p1",
                    "material_signature": group,
                    "sku_ids": [sku_id],
                    "variations": [{"sku_id": sku_id, "price": str(price)}],
                    "coupon_key": "no-coupon",
                },
            },
        )

    sent_group = sku_offer("Banana - Banana", "sku-1", 100)
    same_price_other_group = sku_offer("Conector Y - Plugue de Pino", "sku-2", 100)
    slightly_cheaper = sku_offer("Conector Y - Plugue de Pino", "sku-2", 99.50)
    meaningfully_cheaper = sku_offer("Conector Y - Plugue de Pino", "sku-2", 90)
    snapshot = _snapshot_from_promotion(sent_group)

    assert build_product_key(sent_group) == build_product_key(same_price_other_group)
    assert should_send_promotion(same_price_other_group, [snapshot], 6) is False
    assert should_send_promotion(slightly_cheaper, [snapshot], 6) is False
    assert should_send_promotion(meaningfully_cheaper, [snapshot], 6) is True
    assert should_send_promotion(sent_group, [snapshot], 6) is False
    assert should_send_promotion(
        sku_offer("Banana - Banana", "sku-1", 90),
        [snapshot],
        6,
    ) is True
