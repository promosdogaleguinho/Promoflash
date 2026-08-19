from app.models import MessageAction
from app.sender.whatsapp import WhatsAppSender


def test_whatsapp_accepts_actions_without_type_error():
    sender = WhatsAppSender()
    result = sender.send(
        "chat-1",
        "mensagem",
        actions=[MessageAction(text="Ver", url="https://a")],
    )
    assert result.success is False


def test_whatsapp_returns_not_implemented():
    sender = WhatsAppSender()
    result = sender.send("chat-1", "mensagem")
    assert result.success is False
    assert "not implemented" in (result.error or "").lower()


def test_whatsapp_accepts_legacy_button_kwargs():
    sender = WhatsAppSender()
    result = sender.send(
        "chat-1",
        "mensagem",
        button_url="https://a",
        button_text="Ver",
    )
    assert result.success is False
