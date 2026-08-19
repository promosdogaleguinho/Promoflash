import logging
import time

import httpx

from app.models import MessageAction, SendResult
from app.sender.base import BaseSender

logger = logging.getLogger(__name__)

DEFAULT_BUTTON_TEXT = "🛒 Ver oferta"
MAX_CAPTION_LENGTH = 1024

DEFAULT_MIN_INTERVAL_SECONDS = 1.5
DEFAULT_MAX_RETRIES_ON_RATE_LIMIT = 2
DEFAULT_MAX_RETRY_AFTER_SECONDS = 45


class TelegramSender(BaseSender):
    def __init__(
        self,
        bot_token: str | None,
        dry_run: bool = True,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        max_retries_on_rate_limit: int = DEFAULT_MAX_RETRIES_ON_RATE_LIMIT,
        max_retry_after_seconds: int = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    ) -> None:
        self._bot_token = bot_token
        self._dry_run = dry_run
        self._min_interval_seconds = min_interval_seconds
        self._max_retries_on_rate_limit = max_retries_on_rate_limit
        self._max_retry_after_seconds = max_retry_after_seconds
        self._last_request_monotonic: float | None = None

    def send(
        self,
        chat_id: str,
        message: str,
        image_url: str | None = None,
        actions: list[MessageAction] | None = None,
        button_url: str | None = None,
        button_text: str | None = None,
    ) -> SendResult:
        reply_markup = self._resolve_keyboard(actions, button_url, button_text)
        has_image = bool(image_url)

        if self._dry_run:
            logger.info(
                "[Telegram DRY RUN] chat_id=%s dry_run=true image=%s actions=%s",
                chat_id,
                "set" if has_image else "none",
                len(reply_markup["inline_keyboard"]) if reply_markup else 0,
            )
            return SendResult(success=True, provider_message_id="dry-run")

        token = (self._bot_token or "").strip()
        if not token:
            error = "TELEGRAM_BOT_TOKEN não configurado"
            logger.error(error)
            return SendResult(success=False, error=error)

        self._respect_min_interval()

        if has_image:
            result = self._send_photo(token, chat_id, message, image_url, reply_markup)
            if result.success:
                return result
            logger.warning("Falha ao enviar foto; tentando enviar somente texto.")

        return self._send_text(token, chat_id, message, reply_markup)

    def _respect_min_interval(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        if self._last_request_monotonic is None:
            return
        elapsed = time.monotonic() - self._last_request_monotonic
        remaining = self._min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _resolve_keyboard(
        self,
        actions: list[MessageAction] | None,
        button_url: str | None,
        button_text: str | None,
    ) -> dict | None:
        if actions:
            keyboard = self._build_keyboard_from_actions(actions)
            if keyboard:
                return keyboard
        if button_url:
            return self._build_keyboard(button_url, button_text)
        return None

    @staticmethod
    def _build_keyboard_from_actions(actions: list[MessageAction]) -> dict | None:
        rows: list[list[dict]] = []
        seen_urls: set[str] = set()
        for action in actions:
            if not action.url or action.url in seen_urls:
                continue
            seen_urls.add(action.url)
            rows.append([{"text": action.text or DEFAULT_BUTTON_TEXT, "url": action.url}])
        if not rows:
            return None
        return {"inline_keyboard": rows}

    @staticmethod
    def _build_keyboard(button_url: str | None, button_text: str | None) -> dict:
        return {
            "inline_keyboard": [
                [{"text": button_text or DEFAULT_BUTTON_TEXT, "url": button_url}]
            ]
        }

    def _send_text(
        self, token: str, chat_id: str, message: str, reply_markup: dict | None
    ) -> SendResult:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return self._post(url, payload)

    def _send_photo(
        self,
        token: str,
        chat_id: str,
        message: str,
        image_url: str | None,
        reply_markup: dict | None,
    ) -> SendResult:
        payload = {
            "chat_id": chat_id,
            "photo": image_url,
            "caption": message[:MAX_CAPTION_LENGTH],
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        return self._post(url, payload)

    def _post(self, url: str, payload: dict) -> SendResult:
        attempt = 0
        while True:
            try:
                return self._post_once(url, payload)
            except httpx.HTTPStatusError as exc:
                retry_after = self._retry_after_seconds(exc)
                should_retry = (
                    retry_after is not None
                    and attempt < self._max_retries_on_rate_limit
                    and retry_after <= self._max_retry_after_seconds
                )
                if not should_retry:
                    return self._status_error_result(exc)
                attempt += 1
                logger.warning(
                    "Telegram rate limit (429). Aguardando %ss e tentando novamente "
                    "(%s/%s).",
                    retry_after,
                    attempt,
                    self._max_retries_on_rate_limit,
                )
                time.sleep(retry_after)
            except httpx.HTTPError as exc:
                error = f"Erro ao enviar Telegram: {exc}"
                logger.error(error)
                return SendResult(success=False, error=error)

    def _post_once(self, url: str, payload: dict) -> SendResult:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            self._last_request_monotonic = time.monotonic()
            data = response.json()

            if not data.get("ok"):
                error = data.get("description", "Resposta inválida da API Telegram")
                logger.error("Erro Telegram: %s", error)
                return SendResult(success=False, error=error)

            message_id = str(data.get("result", {}).get("message_id", ""))
            return SendResult(success=True, provider_message_id=message_id)

    @staticmethod
    def _retry_after_seconds(exc: httpx.HTTPStatusError) -> int | None:
        if exc.response.status_code != 429:
            return None
        try:
            payload = exc.response.json()
            retry_after = payload.get("parameters", {}).get("retry_after")
            if retry_after is not None:
                return int(retry_after)
        except (ValueError, TypeError, AttributeError):
            pass
        header_value = exc.response.headers.get("Retry-After")
        if header_value:
            try:
                return int(header_value)
            except ValueError:
                return None
        return None

    @staticmethod
    def _status_error_result(exc: httpx.HTTPStatusError) -> SendResult:
        detail = exc.response.text.strip()
        error = f"Erro HTTP Telegram: {exc.response.status_code}"
        if detail:
            error = f"{error} - {detail}"
        logger.error(error)
        return SendResult(success=False, error=error)
