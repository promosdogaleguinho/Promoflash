from app.message_actions import append_actions_as_text, get_message_actions
from app.models import FormattedMessage, MessageAction


def test_uses_actions_when_present():
    formatted = FormattedMessage(
        text="x",
        actions=[MessageAction(text="Ver", url="https://a")],
    )
    actions = get_message_actions(formatted)
    assert len(actions) == 1
    assert actions[0].url == "https://a"


def test_falls_back_to_offer_url():
    formatted = FormattedMessage(text="x", offer_url="https://legacy", button_text="🛒 Ver oferta")
    actions = get_message_actions(formatted)
    assert len(actions) == 1
    assert actions[0].url == "https://legacy"


def test_removes_actions_without_url():
    formatted = FormattedMessage(
        text="x",
        actions=[MessageAction(text="Ver", url=""), MessageAction(text="Ok", url="https://b")],
    )
    actions = get_message_actions(formatted)
    assert len(actions) == 1
    assert actions[0].url == "https://b"


def test_dedupes_duplicate_urls():
    formatted = FormattedMessage(
        text="x",
        actions=[
            MessageAction(text="A", url="https://same"),
            MessageAction(text="B", url="https://same"),
        ],
    )
    assert len(get_message_actions(formatted)) == 1


def test_truncates_button_text():
    long_text = "x" * 100
    formatted = FormattedMessage(text="x", actions=[MessageAction(text=long_text, url="https://a")])
    actions = get_message_actions(formatted)
    assert len(actions[0].text) <= 40


def test_append_actions_as_text():
    result = append_actions_as_text(
        "Corpo",
        [MessageAction(text="Ver produto", url="https://p")],
    )
    assert "Ver produto:" in result
    assert "https://p" in result


def test_append_actions_as_text_without_actions_returns_original():
    assert append_actions_as_text("Corpo", []) == "Corpo"
