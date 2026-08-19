import logging

from app.models import MessageAction, SendResult
from app.sender.base import BaseSender

logger = logging.getLogger(__name__)


class MockSender(BaseSender):
    def send(
        self,
        chat_id: str,
        message: str,
        image_url: str | None = None,
        actions: list[MessageAction] | None = None,
        button_url: str | None = None,
        button_text: str | None = None,
    ) -> SendResult:
        action_count = len(actions) if actions else (1 if button_url else 0)
        logger.info(
            "Mock send: chat_id=%s image=%s actions=%s",
            chat_id,
            "set" if image_url else "none",
            action_count,
        )
        return SendResult(success=True, provider_message_id="mock-message-id")
