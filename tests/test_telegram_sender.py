import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.models import SendResult
from app.sender.telegram import TelegramSender

logger = logging.getLogger(__name__)


class TestTelegramSender:
    def test_dry_run_returns_success_without_token(self):
        sender = TelegramSender(bot_token=None, dry_run=True)

        result = sender.send("DRY_RUN_GERAL", "mensagem de teste")

        assert result == SendResult(success=True, provider_message_id="dry-run")

    def test_real_mode_without_token_returns_error(self):
        sender = TelegramSender(bot_token=None, dry_run=False)

        result = sender.send("123456", "mensagem de teste")

        assert result.success is False
        assert result.error == "TELEGRAM_BOT_TOKEN não configurado"

    def test_real_mode_with_empty_token_returns_error(self):
        sender = TelegramSender(bot_token="   ", dry_run=False)

        result = sender.send("123456", "mensagem de teste")

        assert result.success is False
        assert result.error == "TELEGRAM_BOT_TOKEN não configurado"

    def test_real_mode_with_mocked_response_returns_success(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 42}}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            result = sender.send("123456", "mensagem de teste")

        assert result.success is True
        assert result.provider_message_id == "42"
        mock_client.post.assert_called_once_with(
            "https://api.telegram.org/botfake-token/sendMessage",
            json={
                "chat_id": "123456",
                "text": "mensagem de teste",
                "disable_web_page_preview": True,
            },
        )

    def test_real_mode_with_button_sends_reply_markup(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 7}}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            result = sender.send(
                "123456",
                "mensagem de teste",
                button_url="https://s.click.aliexpress.com/e/abc",
                button_text="🛒 Ver oferta",
            )

        assert result.success is True
        _, kwargs = mock_client.post.call_args
        payload = kwargs["json"]
        assert payload["reply_markup"] == {
            "inline_keyboard": [
                [
                    {
                        "text": "🛒 Ver oferta",
                        "url": "https://s.click.aliexpress.com/e/abc",
                    }
                ]
            ]
        }

    def test_real_mode_without_button_has_no_reply_markup(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 8}}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            sender.send("123456", "mensagem de teste")

        _, kwargs = mock_client.post.call_args
        assert "reply_markup" not in kwargs["json"]

    def test_real_mode_with_image_uses_send_photo(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 55}}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            result = sender.send(
                "123456",
                "mensagem de teste",
                button_url="https://s.click.aliexpress.com/e/abc",
                button_text="🛒 Ver oferta",
                image_url="https://img.aliexpress.com/produto.jpg",
            )

        assert result.success is True
        args, kwargs = mock_client.post.call_args
        assert args[0] == "https://api.telegram.org/botfake-token/sendPhoto"
        payload = kwargs["json"]
        assert payload["photo"] == "https://img.aliexpress.com/produto.jpg"
        assert payload["caption"] == "mensagem de teste"
        assert payload["reply_markup"]["inline_keyboard"][0][0]["url"] == (
            "https://s.click.aliexpress.com/e/abc"
        )

    def test_real_mode_without_image_uses_send_message(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 56}}
        mock_response.raise_for_status.return_value = None

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.return_value = mock_response

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            sender.send("123456", "mensagem de teste")

        args, _ = mock_client.post.call_args
        assert args[0] == "https://api.telegram.org/botfake-token/sendMessage"

    def test_real_mode_http_error_returns_failure(self):
        sender = TelegramSender(bot_token="fake-token", dry_run=False)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "error",
            request=MagicMock(),
            response=mock_response,
        )

        with patch("app.sender.telegram.httpx.Client", return_value=mock_client):
            result = sender.send("123456", "mensagem de teste")

        assert result.success is False
        assert "Erro HTTP Telegram: 400" in result.error
