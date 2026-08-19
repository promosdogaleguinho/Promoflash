from app.models import MessageAction, SendResult
from app.sender.base import BaseSender


class WhatsAppSender(BaseSender):
    def send(
        self,
        chat_id: str,
        message: str,
        image_url: str | None = None,
        actions: list[MessageAction] | None = None,
        button_url: str | None = None,
        button_text: str | None = None,
    ) -> SendResult:
        # A implementação futura do WhatsApp converterá `MessageAction` no
        # formato adequado: algumas integrações suportam botões nativos e outras
        # exigem links dentro do texto (ver `append_actions_as_text`). O domínio
        # permanece agnóstico e não deve depender das limitações do Telegram.
        return SendResult(success=False, error="WhatsApp sender not implemented yet")
