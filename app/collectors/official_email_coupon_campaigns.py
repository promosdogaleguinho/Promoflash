from datetime import datetime

from app.collectors.coupon_campaign_base import CouponCampaignCollector
from app.models import CouponCampaign


class OfficialEmailCouponCampaignCollector(CouponCampaignCollector):
    """Fonte futura: comunicações oficiais verificadas da AliExpress por e-mail.

    Quando implementada, esta classe deverá:
    - aceitar somente mensagens oficiais verificadas da AliExpress;
    - extrair código, desconto, valor mínimo, validade e URL oficial;
    - normalizar para CouponCampaign;
    - aplicar deduplicação antes do envio.

    Não implementada nesta etapa. Não coleta conteúdo de terceiros.
    """

    def collect(self, now: datetime | None = None) -> list[CouponCampaign]:
        return []
