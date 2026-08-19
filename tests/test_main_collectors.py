import logging

from app.collectors.aliexpress import AliExpressCollector
from app.collectors.awin import AwinCollector
from app.collectors.mock import MockCollector
from app.collectors.shopee import ShopeeCollector
from app.main import _build_collectors
from app.settings import Settings


def _settings(
    app_key: str | None = None,
    app_secret: str | None = None,
    shopee_app_id: str | None = None,
    shopee_app_secret: str | None = None,
    awin_oauth2_token: str | None = None,
    awin_publisher_id: str | None = None,
) -> Settings:
    return Settings(
        app_env="test",
        run_mode="once",
        sleep_interval_seconds=600,
        telegram_bot_token=None,
        telegram_dry_run=True,
        telegram_send_interval_seconds=0.0,
        max_products_per_run=10,
        data_dir="data",
        config_dir="config",
        repost_window_hours=6,
        coupon_repost_window_hours=12,
        aliexpress_app_key=app_key,
        aliexpress_app_secret=app_secret,
        aliexpress_api_endpoint="https://api-sg.aliexpress.com/sync",
        aliexpress_sign_method="hmac",
        aliexpress_tracking_id=None,
        aliexpress_target_currency="BRL",
        aliexpress_target_language="PT",
        aliexpress_ship_to_country="BR",
        shopee_api_url="https://open-api.affiliate.shopee.com.br/graphql",
        shopee_app_id=shopee_app_id,
        shopee_app_secret=shopee_app_secret,
        shopee_request_timeout=30.0,
        shopee_page_limit=20,
        shopee_max_pages=5,
        awin_oauth2_token=awin_oauth2_token,
        awin_publisher_id=awin_publisher_id,
        awin_product_feed_url=None,
        awin_feed_locale="pt_BR",
    )


def _sources(
    mock_enabled: bool,
    aliexpress_enabled: bool,
    shopee_enabled: bool = False,
    awin_enabled: bool = False,
) -> dict:
    return {
        "mock": {"enabled": mock_enabled, "max_items_per_run": 10},
        "aliexpress": {
            "enabled": aliexpress_enabled,
            "max_items_per_run": 20,
            "keywords": ["fone bluetooth"],
        },
        "shopee": {
            "enabled": shopee_enabled,
            "max_items_per_run": 20,
            "keywords": ["notebook"],
        },
        "awin": {
            "enabled": awin_enabled,
            "advertisers": [
                {
                    "id": 17729,
                    "name": "Kabum BR",
                    "display_name": "KaBuM",
                    "enabled": True,
                }
            ],
        },
    }


def test_does_not_break_when_aliexpress_disabled():
    collectors = _build_collectors(_sources(True, False), _settings())

    assert len(collectors) == 1
    assert isinstance(collectors[0], MockCollector)


def test_logs_error_when_aliexpress_enabled_without_credentials(caplog):
    with caplog.at_level(logging.ERROR):
        collectors = _build_collectors(_sources(True, True), _settings())

    assert all(not isinstance(c, AliExpressCollector) for c in collectors)
    assert "ALIEXPRESS_APP_KEY" in caplog.text


def test_builds_aliexpress_with_credentials():
    settings = _settings(app_key="fake-key", app_secret="fake-secret")
    collectors = _build_collectors(_sources(False, True), settings)

    assert len(collectors) == 1
    assert isinstance(collectors[0], AliExpressCollector)


def test_mock_and_aliexpress_together():
    settings = _settings(app_key="fake-key", app_secret="fake-secret")
    collectors = _build_collectors(_sources(True, True), settings)

    assert len(collectors) == 2
    assert any(isinstance(c, MockCollector) for c in collectors)
    assert any(isinstance(c, AliExpressCollector) for c in collectors)


def test_secret_not_logged_when_missing(caplog):
    with caplog.at_level(logging.ERROR):
        _build_collectors(_sources(True, True), _settings())

    assert "fake-secret" not in caplog.text


def test_logs_error_when_shopee_enabled_without_credentials(caplog):
    with caplog.at_level(logging.ERROR):
        collectors = _build_collectors(
            _sources(False, False, shopee_enabled=True),
            _settings(),
        )

    assert all(not isinstance(c, ShopeeCollector) for c in collectors)
    assert "SHOPEE_APP_ID" in caplog.text


def test_builds_shopee_with_credentials():
    settings = _settings(shopee_app_id="shopee-id", shopee_app_secret="shopee-secret")
    collectors = _build_collectors(
        _sources(False, False, shopee_enabled=True),
        settings,
    )

    assert len(collectors) == 1
    assert isinstance(collectors[0], ShopeeCollector)


def test_logs_error_when_awin_enabled_without_credentials(caplog):
    with caplog.at_level(logging.ERROR):
        collectors = _build_collectors(
            _sources(False, False, awin_enabled=True),
            _settings(),
        )

    assert all(not isinstance(c, AwinCollector) for c in collectors)
    assert "AWIN_OAUTH2_TOKEN" in caplog.text


def test_builds_awin_with_credentials():
    settings = _settings(awin_oauth2_token="awin-token", awin_publisher_id="123")
    collectors = _build_collectors(
        _sources(False, False, awin_enabled=True),
        settings,
    )

    assert len(collectors) == 1
    assert isinstance(collectors[0], AwinCollector)
