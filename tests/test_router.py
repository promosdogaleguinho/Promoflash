from app.router import route_promotion

CHANNELS_CONFIG = {
    "telegram": {
        "enabled": True,
        "destinations": {
            "geral": {"chat_id": "DRY_RUN_GERAL", "enabled": True},
            "eletronicos": {"chat_id": "DRY_RUN_ELETRONICOS", "enabled": True},
            "casa": {"chat_id": "DRY_RUN_CASA", "enabled": True},
            "games": {"chat_id": "DRY_RUN_GAMES", "enabled": False},
        },
    },
    "whatsapp": {"enabled": False, "destinations": {}},
}


def test_route_existing_category():
    destinations = route_promotion("eletronicos", CHANNELS_CONFIG)
    assert len(destinations) == 1
    assert destinations[0]["channel"] == "telegram"
    assert destinations[0]["chat_id"] == "DRY_RUN_ELETRONICOS"
    assert destinations[0]["category"] == "eletronicos"


def test_fallback_to_geral():
    destinations = route_promotion("games", CHANNELS_CONFIG)
    assert len(destinations) == 1
    assert destinations[0]["chat_id"] == "DRY_RUN_GERAL"
    assert destinations[0]["category"] == "geral"


def test_moveis_routes_to_casa():
    destinations = route_promotion("moveis", CHANNELS_CONFIG)
    assert len(destinations) == 1
    assert destinations[0]["chat_id"] == "DRY_RUN_CASA"
    assert destinations[0]["category"] == "casa"


def test_roupas_routes_to_moda():
    config = {
        "telegram": {
            "enabled": True,
            "destinations": {
                "geral": {"chat_id": "DRY_RUN_GERAL", "enabled": True},
                "moda": {"chat_id": "DRY_RUN_MODA", "enabled": True},
            },
        }
    }
    destinations = route_promotion("roupas", config)
    assert len(destinations) == 1
    assert destinations[0]["chat_id"] == "DRY_RUN_MODA"
    assert destinations[0]["category"] == "moda"


def test_empty_when_channel_disabled():
    config = {
        "telegram": {"enabled": False, "destinations": {}},
    }
    destinations = route_promotion("eletronicos", config)
    assert destinations == []
