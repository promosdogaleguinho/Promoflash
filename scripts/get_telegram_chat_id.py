import os
import sys

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def _get_bot_token() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Erro: TELEGRAM_BOT_TOKEN não configurado.", file=sys.stderr)
        print("Defina a variável de ambiente antes de executar este script.", file=sys.stderr)
        sys.exit(1)
    return token


def _extract_chat_info(update: dict) -> dict | None:
    for key in ("message", "channel_post", "edited_message", "edited_channel_post"):
        payload = update.get(key)
        if not payload:
            continue
        chat = payload.get("chat")
        if chat:
            return chat
    if update.get("my_chat_member"):
        return update["my_chat_member"].get("chat")
    if update.get("chat_member"):
        return update["chat_member"].get("chat")
    return None


def _format_chat_line(label: str, value: str | None) -> str | None:
    if value:
        return f"{label}: {value}"
    return None


def _print_chat(chat: dict) -> None:
    title = chat.get("title") or chat.get("first_name") or "Sem título"
    chat_type = chat.get("type", "unknown")
    username = chat.get("username")
    chat_id = chat.get("id")

    lines = [
        f"Title: {title}",
        f"Type: {chat_type}",
    ]
    username_line = _format_chat_line("Username", username)
    if username_line:
        lines.append(username_line)
    lines.append(f"Chat ID: {chat_id}")
    print("\n".join(lines))


def main() -> None:
    token = _get_bot_token()
    url = f"{TELEGRAM_API_BASE}{token}/getUpdates"

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        print(f"Erro HTTP ao consultar Telegram: {exc.response.status_code}", file=sys.stderr)
        sys.exit(1)
    except httpx.HTTPError as exc:
        print(f"Erro ao consultar Telegram: {exc}", file=sys.stderr)
        sys.exit(1)

    if not data.get("ok"):
        print(f"Erro da API Telegram: {data.get('description', 'resposta inválida')}", file=sys.stderr)
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        print(
            "Nenhum update encontrado. Envie uma mensagem no grupo/canal "
            "com o bot adicionado e rode novamente."
        )
        return

    seen_chat_ids: set[int] = set()
    chats: list[dict] = []

    for update in updates:
        chat = _extract_chat_info(update)
        if not chat:
            continue
        chat_id = chat.get("id")
        if chat_id is None or chat_id in seen_chat_ids:
            continue
        seen_chat_ids.add(chat_id)
        chats.append(chat)

    if not chats:
        print(
            "Nenhum update encontrado. Envie uma mensagem no grupo/canal "
            "com o bot adicionado e rode novamente."
        )
        return

    print("Found chats:\n")
    for index, chat in enumerate(chats):
        if index > 0:
            print()
        _print_chat(chat)


if __name__ == "__main__":
    main()
