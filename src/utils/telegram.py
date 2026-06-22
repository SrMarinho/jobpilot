import os
from pathlib import Path

import requests
from src.config.settings import logger


def send_telegram(message: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


def send_telegram_photo(path: Path, caption: str = "") -> None:
    """Send a photo file to TELEGRAM_CHAT_ID."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"photo": f},
                timeout=30,
            )
    except Exception as e:
        logger.warning(f"Telegram photo send failed: {e}")


def send_telegram_buttons(message: str, buttons: list) -> int | None:
    """Send a message with an inline keyboard. Returns the message_id or None.

    ``buttons`` is a list of rows, each row a list of ``{"text","data"}`` dicts.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID"))
    if not token or not chat_id:
        return None
    markup = {
        "inline_keyboard": [
            [{"text": b["text"], "callback_data": b["data"]} for b in row]
            for row in buttons
        ]
    }
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "reply_markup": markup,
            },
            timeout=10,
        )
        return resp.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.warning(f"Telegram buttons send failed: {e}")
        return None
