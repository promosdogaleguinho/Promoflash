from abc import ABC, abstractmethod
from datetime import datetime

from app.models import CouponCampaign


class CouponCampaignCollector(ABC):
    """Fonte de campanhas de cupom independentes de produto.

    Fontes previstas:
    - AliExpress Affiliate API
    - configuração manual (config/coupons.json)
    - futuramente: e-mails oficiais da AliExpress
    - futuramente: feed/portal oficial de afiliados

    Não faz parte do domínio desta interface:
    Discord, grupos, scraping, self-bot ou links de terceiros.
    """

    @abstractmethod
    def collect(self, now: datetime | None = None) -> list[CouponCampaign]:
        ...
