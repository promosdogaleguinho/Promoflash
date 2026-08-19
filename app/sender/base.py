from abc import ABC, abstractmethod

from app.models import MessageAction, SendResult


class BaseSender(ABC):
    @abstractmethod
    def send(
        self,
        chat_id: str,
        message: str,
        image_url: str | None = None,
        actions: list[MessageAction] | None = None,
        button_url: str | None = None,
        button_text: str | None = None,
    ) -> SendResult:
        ...
