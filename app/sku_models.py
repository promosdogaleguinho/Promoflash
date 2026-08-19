from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class SkuStatus(str, Enum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


class SkuApiStatus(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    EMPTY = "empty"
    ERROR = "error"


@dataclass
class SkuProperty:
    name: str
    value: str


@dataclass
class SkuVariant:
    sku_id: str
    properties: list[SkuProperty] = field(default_factory=list)
    variation_label: str = ""
    material_signature: str = ""
    cosmetic_label: str = ""
    grouping_dimension: str | None = None
    original_price: Decimal | None = None
    sale_price: Decimal | None = None
    effective_price: Decimal | None = None
    discount_rate: Decimal | None = None
    currency: str | None = None
    image_url: str | None = None
    affiliate_url: str | None = None
    shipping_fee: Decimal | None = None
    delivery_days: int | None = None
    min_delivery_days: int | None = None
    max_delivery_days: int | None = None
    ship_from_country: str | None = None
    availability_status: str = "unknown"
    sku_status: SkuStatus = SkuStatus.UNRESOLVED
    rejection_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkuOfferVariation:
    label: str
    sku_id: str
    price: Decimal
    original_price: Decimal | None = None
    discount_rate: Decimal | None = None
    image_url: str | None = None
    affiliate_url: str | None = None
    grouping_dimension: str | None = None
    shipping_fee: Decimal | None = None
    delivery_days: int | None = None
    min_delivery_days: int | None = None
    max_delivery_days: int | None = None
    ship_from_country: str | None = None


@dataclass
class SkuOfferGroup:
    product_id: str
    material_signature: str
    sku_ids: list[str]
    variations: list[SkuOfferVariation]
    display_price: Decimal
    minimum_price: Decimal
    maximum_price: Decimal
    currency: str
    coupon_key: str = "no-coupon"
    shipping: dict[str, Any] | None = None


@dataclass
class SkuApiResult:
    status: SkuApiStatus
    product_id: str
    skus: list[SkuVariant] = field(default_factory=list)
    item_info: dict[str, Any] = field(default_factory=dict)
    coverage_may_be_incomplete: bool = False
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkuMetrics:
    products_queried: int = 0
    successful_queries: int = 0
    responses_405: int = 0
    other_errors: int = 0
    products_without_sku_data: int = 0
    products_with_one_sku: int = 0
    products_with_multiple_skus: int = 0
    total_skus_returned: int = 0
    responses_with_20_skus: int = 0
    parsed_properties: int = 0
    invalid_properties: int = 0
    resolved_skus: int = 0
    unresolved_skus: int = 0
    rejected_skus: int = 0
    products_without_trusted_skus: int = 0
    aggregate_fallbacks_kept: int = 0
    aggregate_fallbacks_blocked: int = 0
    groups_created: int = 0
    groups_with_multiple_skus: int = 0
    skus_split_by_material: int = 0
    skus_split_by_price: int = 0
    final_sku_offers: int = 0
    delivery_queries: int = 0
    successful_delivery_queries: int = 0
    delivery_failures: int = 0
    missing_skus_in_delivery_response: int = 0
