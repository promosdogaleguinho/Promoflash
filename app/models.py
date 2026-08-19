from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class CouponDiscountType(str, Enum):
    FIXED = "fixed"
    PERCENTAGE = "percentage"
    FREE_SHIPPING = "free_shipping"
    OTHER = "other"


class CouponScopeType(str, Enum):
    PLATFORM = "platform"
    CAMPAIGN = "campaign"
    CATEGORY = "category"
    STORE = "store"
    PRODUCT = "product"
    FULL = "full"
    ORDER = "order"
    UNKNOWN = "unknown"


@dataclass
class Coupon:
    source: str

    code: str | None = None
    title: str | None = None
    description: str | None = None

    discount_type: CouponDiscountType = CouponDiscountType.OTHER
    discount_value: Decimal | None = None
    discount_percentage: Decimal | None = None

    minimum_spend: Decimal | None = None
    maximum_discount: Decimal | None = None

    start_at: datetime | None = None
    end_at: datetime | None = None

    campaign_id: str | None = None
    campaign_name: str | None = None

    scope_type: CouponScopeType = CouponScopeType.UNKNOWN
    scope_value: str | None = None

    app_only: bool = False
    requires_activation: bool = False
    requires_coupon_rescue: bool = False
    requires_coins: bool = False
    coins_amount: int | None = None

    payment_method: str | None = None

    coupon_url: str | None = None
    affiliate_url: str | None = None

    conditions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CouponCampaign:
    source: str
    campaign_id: str
    title: str

    description: str | None = None
    campaign_name: str | None = None

    coupons: list[Coupon] = field(default_factory=list)

    affiliate_url: str | None = None
    campaign_url: str | None = None
    image_url: str | None = None

    category: str | None = None
    tags: list[str] = field(default_factory=list)

    start_at: datetime | None = None
    end_at: datetime | None = None

    announcement_at: datetime | None = None
    announce_before_start: bool = False

    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Promotion:
    external_id: str
    source: str
    title: str
    url: str

    affiliate_url: str | None = None
    tracking_sub_ids: list[str] = field(default_factory=list)

    price: float | None = None
    base_price: float | None = None
    final_price: float | None = None
    old_price: float | None = None
    discount_percentage: float | None = None

    category: str | None = None
    resolved_category: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    store: str | None = None
    seller_id: str | None = None
    seller_name: str | None = None
    is_official_store: bool | None = None
    free_shipping: bool | None = None
    rating: float | None = None
    sales: int | None = None

    image_url: str | None = None

    # Campos legados de cupom (compatibilidade temporária). Preferir `coupons`.
    coupon_code: str | None = None
    coupon_description: str | None = None
    payment_method: str | None = None
    requires_pix: bool = False
    requires_app: bool = False
    price_conditions: list[str] = field(default_factory=list)

    coupons: list["Coupon"] = field(default_factory=list)
    additional_conditions: list[str] = field(default_factory=list)

    canonical_product_id: str | None = None
    product_key: str | None = None

    expires_at: str | None = None

    promotion_tags: list[str] = field(default_factory=list)
    is_official_campaign: bool = False
    campaign_name: str | None = None
    promotion_score: float | None = None

    def __post_init__(self) -> None:
        if not self.coupons and (self.coupon_code or self.coupon_description):
            self.coupons = [
                Coupon(
                    source=self.source,
                    code=self.coupon_code,
                    description=self.coupon_description,
                    metadata={"attachment_reason": "legacy_promotion_fields"},
                )
            ]


@dataclass
class MessageAction:
    text: str
    url: str
    action_type: str = "link"


@dataclass
class FormattedMessage:
    text: str
    image_url: str | None = None
    actions: list[MessageAction] = field(default_factory=list)

    offer_url: str | None = None
    button_text: str | None = "🛒 Ver oferta"


@dataclass
class SendResult:
    success: bool
    provider_message_id: str | None = None
    error: str | None = None


@dataclass
class SentPromotionSnapshot:
    offer_key: str
    product_key: str
    product_price_key: str
    source: str
    external_id: str
    title: str
    price: float | None
    final_price: float | None
    coupon_code: str | None
    payment_method: str | None
    seller_id: str | None
    is_official_store: bool | None
    free_shipping: bool | None
    sent_at: str
    coupon_keys: list[str] = field(default_factory=list)


@dataclass
class SentCouponCampaignSnapshot:
    publication_key: str
    campaign_id: str
    source: str
    coupon_keys: list[str]
    published_at: str
    content_fingerprint: str
    start_at: str | None = None
    end_at: str | None = None
    destination_ids: list[str] = field(default_factory=list)


@dataclass
class CampaignOffer:
    """Oferta de afiliado sem produto enriquecido (ex.: Awin voucher/promotion)."""

    source: str
    external_id: str
    kind: str
    advertiser_id: str
    advertiser_name: str
    advertiser_display_name: str
    title: str
    tracking_url: str

    description: str | None = None
    coupon_code: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: str | None = None
    category: str | None = None
    resolved_category: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    price: float | None = None
    old_price: float | None = None
    image_url: str | None = None
    currency: str | None = None
    merchant_product_id: str | None = None


@dataclass
class SentCampaignOfferSnapshot:
    offer_destination_key: str
    source: str
    advertiser_id: str
    external_id: str
    destination: str
    kind: str
    title: str
    content_fingerprint: str
    published_at: str
