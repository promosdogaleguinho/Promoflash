import os
from dataclasses import dataclass


@dataclass
class Settings:
    app_env: str
    run_mode: str
    sleep_interval_seconds: int
    telegram_bot_token: str | None
    telegram_dry_run: bool
    telegram_send_interval_seconds: float
    max_products_per_run: int
    data_dir: str
    config_dir: str
    repost_window_hours: int
    coupon_repost_window_hours: int
    aliexpress_app_key: str | None
    aliexpress_app_secret: str | None
    aliexpress_api_endpoint: str
    aliexpress_sign_method: str
    aliexpress_tracking_id: str | None
    aliexpress_target_currency: str
    aliexpress_target_language: str
    aliexpress_ship_to_country: str
    shopee_api_url: str
    shopee_app_id: str | None
    shopee_app_secret: str | None
    shopee_request_timeout: float
    shopee_page_limit: int
    shopee_max_pages: int
    awin_oauth2_token: str | None
    awin_publisher_id: str | None
    awin_product_feed_url: str | None
    awin_feed_locale: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.environ.get("APP_ENV", "local"),
            run_mode=os.environ.get("RUN_MODE", "once"),
            sleep_interval_seconds=int(os.environ.get("SLEEP_INTERVAL_SECONDS", "600")),
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_dry_run=os.environ.get("TELEGRAM_DRY_RUN", "true").lower()
            in ("true", "1", "yes"),
            telegram_send_interval_seconds=float(
                os.environ.get("TELEGRAM_SEND_INTERVAL_SECONDS", "1.5")
            ),
            max_products_per_run=int(os.environ.get("MAX_PRODUCTS_PER_RUN", "20")),
            data_dir=os.environ.get("DATA_DIR", "data"),
            config_dir=os.environ.get("CONFIG_DIR", "config"),
            repost_window_hours=int(os.environ.get("REPOST_WINDOW_HOURS", "24")),
            coupon_repost_window_hours=int(
                os.environ.get("COUPON_REPOST_WINDOW_HOURS", "12")
            ),
            aliexpress_app_key=os.environ.get("ALIEXPRESS_APP_KEY") or None,
            aliexpress_app_secret=os.environ.get("ALIEXPRESS_APP_SECRET") or None,
            aliexpress_api_endpoint=os.environ.get(
                "ALIEXPRESS_API_ENDPOINT", "https://api-sg.aliexpress.com/sync"
            ),
            aliexpress_sign_method=os.environ.get("ALIEXPRESS_SIGN_METHOD", "hmac"),
            aliexpress_tracking_id=os.environ.get("ALIEXPRESS_TRACKING_ID") or None,
            aliexpress_target_currency=os.environ.get("ALIEXPRESS_TARGET_CURRENCY", "BRL"),
            aliexpress_target_language=os.environ.get("ALIEXPRESS_TARGET_LANGUAGE", "PT"),
            aliexpress_ship_to_country=os.environ.get("ALIEXPRESS_SHIP_TO_COUNTRY", "BR"),
            shopee_api_url=os.environ.get(
                "SHOPEE_API_URL",
                "https://open-api.affiliate.shopee.com.br/graphql",
            ),
            shopee_app_id=os.environ.get("SHOPEE_APP_ID") or None,
            shopee_app_secret=os.environ.get("SHOPEE_APP_SECRET") or None,
            shopee_request_timeout=float(
                os.environ.get("SHOPEE_REQUEST_TIMEOUT", "30")
            ),
            shopee_page_limit=int(os.environ.get("SHOPEE_PAGE_LIMIT", "20")),
            shopee_max_pages=int(os.environ.get("SHOPEE_MAX_PAGES", "5")),
            awin_oauth2_token=os.environ.get("AWIN_OAUTH2_TOKEN") or None,
            awin_publisher_id=os.environ.get("AWIN_PUBLISHER_ID") or None,
            awin_product_feed_url=os.environ.get("AWIN_PRODUCT_FEED_URL") or None,
            awin_feed_locale=os.environ.get("AWIN_FEED_LOCALE", "pt_BR"),
        )
