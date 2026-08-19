import logging

from app.models import MessageAction
from app.sender.mock import MockSender


def test_mock_sender_accepts_actions():
    sender = MockSender()
    result = sender.send(
        "chat-1",
        "mensagem",
        actions=[
            MessageAction(text="🛒 Ver produto", url="https://a"),
            MessageAction(text="🎟️ Resgatar cupom", url="https://b"),
        ],
    )
    assert result.success is True


def test_mock_sender_logs_action_count_without_links(caplog):
    sender = MockSender()
    with caplog.at_level(logging.INFO):
        sender.send(
            "chat-1",
            "mensagem",
            actions=[MessageAction(text="Ver", url="https://secret-link.example.com")],
        )
    assert "actions=1" in caplog.text
    assert "https://secret-link.example.com" not in caplog.text


def test_mock_sender_accepts_button_without_breaking():
    sender = MockSender()

    result = sender.send(
        "chat-1",
        "mensagem",
        button_url="https://s.click.aliexpress.com/e/abc",
        button_text="🛒 Ver oferta",
    )

    assert result.success is True
    assert result.provider_message_id == "mock-message-id"


def test_mock_sender_works_without_button():
    sender = MockSender()

    result = sender.send("chat-1", "mensagem")

    assert result.success is True


def test_mock_sender_accepts_image_without_breaking():
    sender = MockSender()

    result = sender.send(
        "chat-1",
        "mensagem",
        button_url="https://s.click.aliexpress.com/e/abc",
        image_url="https://img.aliexpress.com/produto.jpg",
    )

    assert result.success is True
