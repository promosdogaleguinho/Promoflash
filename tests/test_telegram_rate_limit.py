from unittest.mock import MagicMock, patch

import httpx

from app.sender.telegram import TelegramSender


def _rate_limited_response(retry_after: int) -> MagicMock:
    response = MagicMock()
    response.status_code = 429
    response.text = "Too Many Requests"
    response.json.return_value = {
        "ok": False,
        "error_code": 429,
        "parameters": {"retry_after": retry_after},
    }
    return response


def _ok_response(message_id: int) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    response.raise_for_status.return_value = None
    return response


def test_retries_after_429_and_succeeds():
    sender = TelegramSender(
        bot_token="fake-token",
        dry_run=False,
        min_interval_seconds=0.0,
        max_retries_on_rate_limit=2,
        max_retry_after_seconds=45,
    )

    error = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=_rate_limited_response(1)
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = [error, _ok_response(10)]

    with patch("app.sender.telegram.httpx.Client", return_value=client), patch(
        "app.sender.telegram.time.sleep"
    ) as sleep_mock:
        result = sender.send("123", "msg")

    assert result.success is True
    assert client.post.call_count == 2
    sleep_mock.assert_called_once_with(1)


def test_gives_up_when_retry_after_exceeds_cap():
    sender = TelegramSender(
        bot_token="fake-token",
        dry_run=False,
        min_interval_seconds=0.0,
        max_retries_on_rate_limit=3,
        max_retry_after_seconds=30,
    )

    error = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=_rate_limited_response(120)
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = error

    with patch("app.sender.telegram.httpx.Client", return_value=client), patch(
        "app.sender.telegram.time.sleep"
    ) as sleep_mock:
        result = sender.send("123", "msg")

    assert result.success is False
    assert "429" in result.error
    assert client.post.call_count == 1
    sleep_mock.assert_not_called()


def test_stops_after_max_retries():
    sender = TelegramSender(
        bot_token="fake-token",
        dry_run=False,
        min_interval_seconds=0.0,
        max_retries_on_rate_limit=2,
        max_retry_after_seconds=45,
    )

    error = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=_rate_limited_response(1)
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = error

    with patch("app.sender.telegram.httpx.Client", return_value=client), patch(
        "app.sender.telegram.time.sleep"
    ):
        result = sender.send("123", "msg")

    assert result.success is False
    assert client.post.call_count == 3


def test_min_interval_sleeps_between_sends():
    sender = TelegramSender(
        bot_token="fake-token",
        dry_run=False,
        min_interval_seconds=1.5,
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _ok_response(1)

    with patch("app.sender.telegram.httpx.Client", return_value=client), patch(
        "app.sender.telegram.time.sleep"
    ) as sleep_mock, patch(
        "app.sender.telegram.time.monotonic", side_effect=[100.0, 100.2, 101.7]
    ):
        sender.send("123", "primeira")
        sender.send("123", "segunda")

    sleep_mock.assert_called_once()
    assert sleep_mock.call_args[0][0] > 0


def test_first_send_does_not_sleep():
    sender = TelegramSender(
        bot_token="fake-token",
        dry_run=False,
        min_interval_seconds=1.5,
    )

    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = _ok_response(1)

    with patch("app.sender.telegram.httpx.Client", return_value=client), patch(
        "app.sender.telegram.time.sleep"
    ) as sleep_mock, patch("app.sender.telegram.time.monotonic", return_value=100.0):
        sender.send("123", "primeira")

    sleep_mock.assert_not_called()
