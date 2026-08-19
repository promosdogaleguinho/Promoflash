from unittest.mock import MagicMock

from app.collectors.aliexpress_api_coupon_campaigns import (
    AliExpressApiCouponCampaignCollector,
)
from app.collectors.official_email_coupon_campaigns import (
    OfficialEmailCouponCampaignCollector,
)
from app.models import CouponCampaign


def _campaign(name: str = "Weekly Deals", promotion_id: str = "w1") -> dict:
    return {
        "promotion_id": promotion_id,
        "promotion_name": name,
        "raw": {},
    }


def _campaign_with_coupon(
    name: str = "Weekly Deals",
    promotion_id: str = "w1",
    code: str = "CAMP10",
) -> dict:
    campaign = _campaign(name, promotion_id)
    campaign["raw"] = {
        "promo_code_info": {
            "promo_code": code,
            "code_value": "R$ 10 OFF",
            "code_mini_spend": "50",
        }
    }
    return campaign


def test_does_not_publish_product_coupon_as_campaign_coupon():
    client = MagicMock()
    client.featured_promo_get.return_value = [_campaign()]
    client.featured_promo_products_get.return_value = [
        {"product_id": "100", "product_title": "Item"}
    ]
    client.product_detail_get.return_value = [
        {
            "product_id": "100",
            "promo_code_info": {
                "promo_code": "GMG20207",
                "code_value": "On order over USD 10, get USD 7 off",
                "code_mini_spend": "10",
                "code_promotionurl": "https://s.click.aliexpress.com/e/_x",
                "code_availabletime_start": "2030-01-01 00:00:00",
                "code_availabletime_end": "2030-12-31 23:59:59",
            },
        }
    ]

    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 3,
            "max_items_per_campaign": 5,
            "max_product_details_per_run": 5,
            "allowed_campaigns": [],
        },
    )

    assert collector.collect() == []
    client.featured_promo_products_get.assert_not_called()
    client.product_detail_get.assert_not_called()


def test_does_not_invent_campaign_without_coupons():
    client = MagicMock()
    client.featured_promo_get.return_value = [_campaign()]
    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={"allowed_campaigns": []},
    )

    assert collector.collect() == []


def test_extracts_campaign_level_coupon_from_campaign_raw():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        {
            "promotion_id": "c1",
            "promotion_name": "Weekly Deals",
            "raw": {
                "promo_code_info": {
                    "promo_code": "CAMP10",
                    "code_value": "R$ 10 OFF",
                    "code_mini_spend": "50",
                }
            },
        }
    ]
    client.featured_promo_products_get.return_value = []
    client.product_detail_get.return_value = []

    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={"allowed_campaigns": []},
    )
    campaigns = collector.collect()
    assert len(campaigns) == 1
    assert isinstance(campaigns[0], CouponCampaign)
    assert campaigns[0].coupons[0].code == "CAMP10"
    client.featured_promo_products_get.assert_not_called()
    client.product_detail_get.assert_not_called()


def test_replaces_internal_campaign_name_in_public_message():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign_with_coupon("AEB_BR_Internal_20241114")
    ]
    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={"allowed_campaigns": []},
    )
    assert collector.collect()[0].title == "Cupons AliExpress"


def test_respects_allowed_campaigns_filter():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign_with_coupon("Weekly Deals", code="WEEK10"),
        _campaign_with_coupon("Unknown Promo", "u1", "UNKNOWN10"),
    ]

    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={"allowed_campaigns": ["Weekly Deals"]},
    )
    campaigns = collector.collect()
    assert [campaign.coupons[0].code for campaign in campaigns] == ["WEEK10"]


def test_falls_back_when_allowed_campaigns_miss_all_names():
    client = MagicMock()
    client.featured_promo_get.return_value = [
        _campaign_with_coupon("Promo BR Local", "br1"),
    ]

    collector = AliExpressApiCouponCampaignCollector(
        client=client,
        source_config={
            "max_campaigns_per_run": 1,
            "allowed_campaigns": ["Hot Product", "Weekly Deals"],
        },
    )
    campaigns = collector.collect()
    assert [campaign.title for campaign in campaigns] == ["Promo BR Local"]

def test_featured_failure_does_not_raise():
    client = MagicMock()
    client.featured_promo_get.side_effect = RuntimeError("boom")

    collector = AliExpressApiCouponCampaignCollector(client=client)
    assert collector.collect() == []


def test_official_email_collector_is_stubbed():
    collector = OfficialEmailCouponCampaignCollector()
    assert collector.collect() == []
