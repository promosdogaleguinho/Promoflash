from app.campaigns import get_campaign_display_name


def test_hot_product_becomes_produto_em_alta():
    assert get_campaign_display_name("Hot Product") == "Produto em alta"


def test_new_arrival_becomes_novidade():
    assert get_campaign_display_name("New Arrival") == "Novidade"


def test_best_seller_becomes_mais_vendido():
    assert get_campaign_display_name("Best Seller") == "Mais vendido"


def test_weekly_deals_becomes_oferta_da_semana():
    assert get_campaign_display_name("Weekly Deals") == "Oferta da semana"


def test_comparison_ignores_case():
    assert get_campaign_display_name("hot product") == "Produto em alta"
    assert get_campaign_display_name("HOT PRODUCT") == "Produto em alta"


def test_comparison_tolerates_hyphen():
    assert get_campaign_display_name("hot-product") == "Produto em alta"


def test_comparison_tolerates_underscore():
    assert get_campaign_display_name("hot_product") == "Produto em alta"


def test_comparison_tolerates_extra_spaces():
    assert get_campaign_display_name("  hot   product  ") == "Produto em alta"


def test_unknown_name_is_sanitized():
    result = get_campaign_display_name("  Choice   Day  ")
    assert result == "Choice Day"


def test_ship_from_br_internal_name_becomes_public_name():
    result = get_campaign_display_name("AEB_BR_ShipFromBR_20241114")
    assert result == "Envio do Brasil"


def test_selected_items_internal_name_becomes_public_name():
    result = get_campaign_display_name("AEB_BR_DropiSelectedItems_20241106")
    assert result == "Itens selecionados"


def test_unknown_aliexpress_internal_name_uses_generic_name():
    result = get_campaign_display_name("AEB_BR_InternalCampaign_20260101")
    assert result == "Campanha AliExpress"


def test_unknown_long_name_is_truncated():
    long_name = "A" * 100
    result = get_campaign_display_name(long_name)
    assert len(result) <= 40
    assert result


def test_empty_name_does_not_break():
    assert get_campaign_display_name("") == ""
    assert get_campaign_display_name("   ") == ""
