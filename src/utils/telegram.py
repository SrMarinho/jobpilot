import os
from pathlib import Path

import requests
from src.config.settings import logger


def _thread(topic: str | None) -> int | None:
    from src.core.use_cases.telegram_topics import resolve_thread_id

    return resolve_thread_id(topic)


def send_telegram(message: str, topic: str | None = None) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return

    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    thread = _thread(topic)
    if thread:
        payload["message_thread_id"] = thread
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")


def send_telegram_photo(
    path: Path, caption: str = "", topic: str | None = None
) -> None:
    """Send a photo file to TELEGRAM_CHAT_ID."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
    thread = _thread(topic)
    if thread:
        data["message_thread_id"] = thread
    try:
        with open(path, "rb") as f:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data=data,
                files={"photo": f},
                timeout=30,
            )
    except Exception as e:
        logger.warning(f"Telegram photo send failed: {e}")


def send_telegram_media_group(
    paths: list, caption: str = "", topic: str | None = None
) -> None:
    """Envia várias fotos como um álbum único (sendMediaGroup). Até 10 imagens.

    A ``caption`` (HTML) vai na primeira foto. ``topic`` roteia pro tópico certo.
    """
    import json as _json

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    paths = list(paths)[:10]
    if not paths:
        return
    media, files = [], {}
    for i, p in enumerate(paths):
        attach = f"photo{i}"
        item = {"type": "photo", "media": f"attach://{attach}"}
        if i == 0 and caption:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)
        files[attach] = open(p, "rb")
    data = {"chat_id": chat_id, "media": _json.dumps(media)}
    thread = _thread(topic)
    if thread:
        data["message_thread_id"] = thread
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMediaGroup",
            data=data,
            files=files,
            timeout=60,
        )
    except Exception as e:
        logger.warning(f"Telegram media group send failed: {e}")
    finally:
        for f in files.values():
            try:
                f.close()
            except Exception:
                pass


def send_telegram_photo_buttons(
    path: Path, caption: str, buttons: list, topic: str | None = None
) -> int | None:
    """sendPhoto com teclado inline (aprovação com imagem). Returns message_id."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    thread = _thread(topic)
    chat_id = (
        os.getenv("TELEGRAM_CHAT_ID")
        if thread
        else os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID"))
    )
    if not token or not chat_id:
        return None
    import json as _json

    markup = {
        "inline_keyboard": [
            [{"text": b["text"], "callback_data": b["data"]} for b in row]
            for row in buttons
        ]
    }
    data = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
        # sendPhoto é multipart: reply_markup vai como string JSON.
        "reply_markup": _json.dumps(markup),
    }
    if thread:
        data["message_thread_id"] = thread
    try:
        with open(path, "rb") as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data=data,
                files={"photo": f},
                timeout=30,
            )
        return resp.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.warning(f"Telegram photo+buttons send failed: {e}")
        return None


def send_telegram_buttons(
    message: str, buttons: list, topic: str | None = None
) -> int | None:
    """Send a message with an inline keyboard. Returns the message_id or None.

    ``buttons`` is a list of rows, each row a list of ``{"text","data"}`` dicts.
    Com ``topic``, roteia pro grupo (chat_id) na sessão; sem, mantém o DM ao admin.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    thread = _thread(topic)
    chat_id = (
        os.getenv("TELEGRAM_CHAT_ID")
        if thread
        else os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID"))
    )
    if not token or not chat_id:
        return None
    markup = {
        "inline_keyboard": [
            [{"text": b["text"], "callback_data": b["data"]} for b in row]
            for row in buttons
        ]
    }
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "reply_markup": markup,
    }
    if thread:
        payload["message_thread_id"] = thread
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=10,
        )
        return resp.json().get("result", {}).get("message_id")
    except Exception as e:
        logger.warning(f"Telegram buttons send failed: {e}")
        return None
