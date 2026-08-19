import logging
from unittest.mock import MagicMock, patch

import httpx

from app.models import MessageAction
from app.sender.telegram import TelegramSender


def _mock_client(json_result: dict) -> MagicMock:
    mock_response = MagicMock()
    mock_response.json.return_value = {"ok": True, "result": json_result}
    mock_response.raise_for_status.return_value = None

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response
    return mock_client


def test_single_action_creates_single_button():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 1})
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send("123", "msg", actions=[MessageAction(text="🛒 Ver produto", url="https://p")])
    _, kwargs = client.post.call_args
    keyboard = kwargs["json"]["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1
    assert keyboard[0][0]["url"] == "https://p"


def test_two_actions_create_two_buttons():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 2})
    actions = [
        MessageAction(text="🛒 Ver produto", url="https://p"),
        MessageAction(text="🎟️ Resgatar cupom", url="https://c"),
    ]
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send("123", "msg", actions=actions)
    keyboard = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 2


def test_actions_work_in_send_photo():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 3})
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send(
            "123",
            "msg",
            image_url="https://img",
            actions=[MessageAction(text="🛒 Ver produto", url="https://p")],
        )
    args, kwargs = client.post.call_args
    assert args[0].endswith("/sendPhoto")
    assert "reply_markup" in kwargs["json"]


def test_duplicate_action_is_removed():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 4})
    actions = [
        MessageAction(text="A", url="https://same"),
        MessageAction(text="B", url="https://same"),
    ]
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send("123", "msg", actions=actions)
    keyboard = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1


def test_action_without_url_is_ignored():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 5})
    actions = [
        MessageAction(text="A", url=""),
        MessageAction(text="B", url="https://b"),
    ]
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send("123", "msg", actions=actions)
    keyboard = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    assert len(keyboard) == 1
    assert keyboard[0][0]["url"] == "https://b"


def test_image_fallback_preserves_actions():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)

    ok_response = MagicMock()
    ok_response.json.return_value = {"ok": True, "result": {"message_id": 6}}
    ok_response.raise_for_status.return_value = None

    error_response = MagicMock()
    error_response.status_code = 400
    error_response.text = "Bad Request"

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = [
        httpx.HTTPStatusError("err", request=MagicMock(), response=error_response),
        ok_response,
    ]

    with patch("app.sender.telegram.httpx.Client", return_value=client):
        result = sender.send(
            "123",
            "msg",
            image_url="https://img",
            actions=[MessageAction(text="🛒 Ver produto", url="https://p")],
        )

    assert result.success is True
    last_args, last_kwargs = client.post.call_args
    assert last_args[0].endswith("/sendMessage")
    assert "reply_markup" in last_kwargs["json"]


def test_legacy_button_still_works():
    sender = TelegramSender(bot_token="fake-token", dry_run=False)
    client = _mock_client({"message_id": 7})
    with patch("app.sender.telegram.httpx.Client", return_value=client):
        sender.send("123", "msg", button_url="https://legacy", button_text="🛒 Ver oferta")
    keyboard = client.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    assert keyboard[0][0]["url"] == "https://legacy"


def test_dry_run_does_not_log_urls(caplog):
    sender = TelegramSender(bot_token=None, dry_run=True)
    with caplog.at_level(logging.INFO):
        sender.send(
            "123",
            "msg",
            actions=[MessageAction(text="Ver", url="https://secret-url.example.com")],
        )
    assert "https://secret-url.example.com" not in caplog.text
