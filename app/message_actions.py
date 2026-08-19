from app.models import FormattedMessage, MessageAction

MAX_BUTTON_TEXT_LENGTH = 40
DEFAULT_MAX_ACTIONS = 5


def _dedupe_actions(actions: list[MessageAction]) -> list[MessageAction]:
    unique: list[MessageAction] = []
    seen_urls: set[str] = set()
    for action in actions:
        if not action.url:
            continue
        if action.url in seen_urls:
            continue
        seen_urls.add(action.url)
        text = (action.text or "").strip()[:MAX_BUTTON_TEXT_LENGTH]
        unique.append(
            MessageAction(text=text, url=action.url, action_type=action.action_type)
        )
    return unique


def get_message_actions(
    formatted: FormattedMessage,
    max_actions: int = DEFAULT_MAX_ACTIONS,
) -> list[MessageAction]:
    if formatted.actions:
        actions = list(formatted.actions)
    elif formatted.offer_url:
        actions = [
            MessageAction(
                text=formatted.button_text or "🛒 Ver oferta",
                url=formatted.offer_url,
                action_type="link",
            )
        ]
    else:
        actions = []

    deduped = _dedupe_actions(actions)
    return deduped[:max_actions]


def append_actions_as_text(text: str, actions: list[MessageAction]) -> str:
    valid_actions = _dedupe_actions(actions)
    if not valid_actions:
        return text

    lines = [text, ""]
    for action in valid_actions:
        label = (action.text or "Acessar").strip()
        lines.append(f"{label}:")
        lines.append(action.url)
        lines.append("")

    return "\n".join(lines).rstrip()
