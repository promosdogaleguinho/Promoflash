from app.campaign_selection import select_featured_campaigns


def test_selects_allowed_campaigns_when_present():
    campaigns = [
        {"promotion_name": "Weekly Deals", "promotion_id": "1"},
        {"promotion_name": "Random Sale", "promotion_id": "2"},
    ]
    selected = select_featured_campaigns(
        campaigns,
        max_campaigns=3,
        allowed_campaigns=["Weekly Deals"],
    )
    assert len(selected) == 1
    assert selected[0]["promotion_name"] == "Weekly Deals"


def test_falls_back_when_allowed_names_do_not_match(caplog):
    campaigns = [
        {"promotion_name": "Promo BR A", "promotion_id": "a"},
        {"promotion_name": "Promo BR B", "promotion_id": "b"},
    ]
    with caplog.at_level("WARNING"):
        selected = select_featured_campaigns(
            campaigns,
            max_campaigns=1,
            allowed_campaigns=["Hot Product", "Weekly Deals"],
        )
    assert len(selected) == 1
    assert selected[0]["promotion_name"] == "Promo BR A"
    assert any("Nenhuma campanha bateu" in record.message for record in caplog.records)


def test_empty_allowed_selects_first_campaigns():
    campaigns = [
        {"promotion_name": "A", "promotion_id": "1"},
        {"promotion_name": "B", "promotion_id": "2"},
        {"promotion_name": "C", "promotion_id": "3"},
    ]
    selected = select_featured_campaigns(
        campaigns,
        max_campaigns=2,
        allowed_campaigns=[],
    )
    assert [item["promotion_name"] for item in selected] == ["A", "B"]


def test_blocked_campaigns_are_excluded_from_fallback():
    campaigns = [
        {"promotion_name": "Blocked", "promotion_id": "1"},
        {"promotion_name": "Ok", "promotion_id": "2"},
    ]
    selected = select_featured_campaigns(
        campaigns,
        max_campaigns=2,
        allowed_campaigns=["Missing"],
        blocked_campaigns=["Blocked"],
    )
    assert len(selected) == 1
    assert selected[0]["promotion_name"] == "Ok"


def test_preferred_patterns_rank_before_others():
    campaigns = [
        {
            "promotion_name": "0203-Knasta-202602-PE",
            "promotion_id": "1",
            "raw": {"product_num": 28021},
        },
        {
            "promotion_name": "AEB_BR_ShipFromBR_20241114",
            "promotion_id": "2",
            "raw": {"product_num": 47179},
        },
        {
            "promotion_name": "0713-0719 Vacation sale- Top Brands",
            "promotion_id": "3",
            "raw": {"product_num": 2691},
        },
    ]
    selected = select_featured_campaigns(
        campaigns,
        max_campaigns=2,
        preferred_patterns=["AEB_BR_", "Vacation sale"],
    )
    assert [item["promotion_name"] for item in selected] == [
        "AEB_BR_ShipFromBR_20241114",
        "0713-0719 Vacation sale- Top Brands",
    ]


def test_blocked_patterns_exclude_matches():
    campaigns = [
        {"promotion_name": "AEB_ClawEden_SexItem_20241206", "promotion_id": "1"},
        {"promotion_name": "AEB_BR_ShipFromBR", "promotion_id": "2"},
    ]
    selected = select_featured_campaigns(
        campaigns,
        max_campaigns=2,
        preferred_patterns=["AEB_BR_"],
        blocked_patterns=["SexItem"],
    )
    assert len(selected) == 1
    assert selected[0]["promotion_name"] == "AEB_BR_ShipFromBR"
