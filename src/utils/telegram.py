import asyncio
import atexit
import json as _json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable

import requests
from src.config.settings import logger

_API = "https://api.telegram.org/bot{token}/{method}"
_RETRIES = 3
_BACKOFF_S = 2
_MAX_RETRY_AFTER_S = 60

# Notificações são fire-and-forget. Chamadas de dentro de corrotina, o POST
# síncrono (até 60s + retries) travaria o event loop e, com ele, o browser —
# então despachamos pra uma thread e voltamos na hora. O atexit garante que o
# envio termina antes do processo morrer.
_notify_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="telegram")
atexit.register(lambda: _notify_pool.shutdown(wait=True))


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def _fire_and_forget(fn: Callable[..., Any], *args: Any) -> None:
    """Roda ``fn`` fora do event loop se houver um; senão, inline."""
    if _in_event_loop():
        _notify_pool.submit(fn, *args)
    else:
        fn(*args)


def _thread(topic: str | None) -> int | None:
    from src.core.use_cases.telegram_topics import resolve_thread_id

    return resolve_thread_id(topic)


def _token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str | None:
    return os.getenv("TELEGRAM_CHAT_ID")


def _admin_chat_id(thread: int | None) -> str | None:
    """Com tópico, roteia pro grupo; sem, mantém o DM ao admin."""
    if thread:
        return _chat_id()
    return os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID"))


def _retry_after(resp: requests.Response) -> float:
    """Segundos pedidos pelo Telegram num 429, limitados a _MAX_RETRY_AFTER_S."""
    try:
        wait = float(resp.json().get("parameters", {}).get("retry_after", 0))
    except Exception:
        wait = 0
    if wait <= 0:
        wait = float(resp.headers.get("Retry-After", 0) or 0)
    return min(wait, _MAX_RETRY_AFTER_S) if wait > 0 else 0


def _post(
    method: str,
    *,
    label: str,
    json: dict | None = None,
    data: dict | None = None,
    files: Callable[[ExitStack], dict] | None = None,
    timeout: int = 10,
) -> dict | None:
    """POST na Bot API com raise_for_status + retry com backoff em 429/5xx.

    ``files`` é uma factory que recebe um ExitStack e devolve o dict de arquivos —
    precisa ser reaberto a cada tentativa, por isso não é um dict pronto.
    Retorna o corpo JSON da resposta, ou ``None`` se falhou/não configurado.
    """
    token = _token()
    if not token:
        return None
    url = _API.format(token=token, method=method)

    for attempt in range(_RETRIES):
        try:
            with ExitStack() as stack:
                resp = requests.post(
                    url,
                    json=json,
                    data=data,
                    files=files(stack) if files else None,
                    timeout=timeout,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < _RETRIES - 1:
                    wait = _retry_after(resp) or _BACKOFF_S * (2**attempt)
                    logger.warning(
                        f"Telegram {label}: HTTP {resp.status_code}, "
                        f"retry em {wait:.0f}s ({attempt + 1}/{_RETRIES})"
                    )
                    time.sleep(wait)
                    continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt < _RETRIES - 1:
                wait = _BACKOFF_S * (2**attempt)
                logger.warning(f"Telegram {label} falhou ({e}), retry em {wait}s")
                time.sleep(wait)
                continue
            logger.warning(f"Telegram {label} failed: {e}")
        except Exception as e:
            logger.warning(f"Telegram {label} failed: {e}")
            break
    return None


def _message_id(result: dict | None) -> int | None:
    if not result:
        return None
    return result.get("result", {}).get("message_id")


def _markup(buttons: list) -> dict:
    return {
        "inline_keyboard": [
            [{"text": b["text"], "callback_data": b["data"]} for b in row]
            for row in buttons
        ]
    }


def _with_thread(payload: dict, topic: str | None) -> dict:
    thread = _thread(topic)
    if thread:
        payload["message_thread_id"] = thread
    return payload


def _send_message(message: str, topic: str | None) -> None:
    chat_id = _chat_id()
    if not chat_id:
        return
    payload = _with_thread(
        {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, topic
    )
    _post("sendMessage", label="notification", json=payload)


def send_telegram(message: str, topic: str | None = None) -> None:
    """Notificação fire-and-forget — seguro de chamar de dentro de corrotina."""
    _fire_and_forget(_send_message, message, topic)


async def send_telegram_async(message: str, topic: str | None = None) -> None:
    """Igual a ``send_telegram``, mas espera o envio terminar sem travar o loop."""
    await asyncio.to_thread(_send_message, message, topic)


def _send_photo(path: Path, caption: str, topic: str | None) -> None:
    chat_id = _chat_id()
    if not chat_id:
        return
    data = _with_thread(
        {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}, topic
    )
    _post(
        "sendPhoto",
        label="photo",
        data=data,
        files=lambda stack: {"photo": stack.enter_context(open(path, "rb"))},
        timeout=30,
    )


def send_telegram_photo(
    path: Path, caption: str = "", topic: str | None = None
) -> None:
    """Send a photo file to TELEGRAM_CHAT_ID (fire-and-forget)."""
    _fire_and_forget(_send_photo, path, caption, topic)


def _send_media_group(paths: list, caption: str, topic: str | None) -> None:
    chat_id = _chat_id()
    if not chat_id:
        return
    paths = list(paths)[:10]
    if not paths:
        return
    media: list[dict[str, Any]] = []
    for i, _ in enumerate(paths):
        item: dict[str, Any] = {"type": "photo", "media": f"attach://photo{i}"}
        if i == 0 and caption:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media.append(item)
    data = _with_thread({"chat_id": chat_id, "media": _json.dumps(media)}, topic)
    _post(
        "sendMediaGroup",
        label="media group",
        data=data,
        files=lambda stack: {
            f"photo{i}": stack.enter_context(open(p, "rb")) for i, p in enumerate(paths)
        },
        timeout=60,
    )


def send_telegram_media_group(
    paths: list, caption: str = "", topic: str | None = None
) -> None:
    """Envia várias fotos como um álbum único (sendMediaGroup). Até 10 imagens.

    A ``caption`` (HTML) vai na primeira foto. ``topic`` roteia pro tópico certo.
    Fire-and-forget.
    """
    _fire_and_forget(_send_media_group, paths, caption, topic)


def send_telegram_photo_buttons(
    path: Path, caption: str, buttons: list, topic: str | None = None
) -> int | None:
    """sendPhoto com teclado inline (aprovação com imagem). Returns message_id."""
    chat_id = _admin_chat_id(_thread(topic))
    if not chat_id:
        return None
    data = _with_thread(
        {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "HTML",
            # sendPhoto é multipart: reply_markup vai como string JSON.
            "reply_markup": _json.dumps(_markup(buttons)),
        },
        topic,
    )
    return _message_id(
        _post(
            "sendPhoto",
            label="photo+buttons",
            data=data,
            files=lambda stack: {"photo": stack.enter_context(open(path, "rb"))},
            timeout=30,
        )
    )


def send_telegram_buttons(
    message: str, buttons: list, topic: str | None = None
) -> int | None:
    """Send a message with an inline keyboard. Returns the message_id or None.

    ``buttons`` is a list of rows, each row a list of ``{"text","data"}`` dicts.
    Com ``topic``, roteia pro grupo (chat_id) na sessão; sem, mantém o DM ao admin.
    """
    chat_id = _admin_chat_id(_thread(topic))
    if not chat_id:
        return None
    payload = _with_thread(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "reply_markup": _markup(buttons),
        },
        topic,
    )
    return _message_id(_post("sendMessage", label="buttons", json=payload))


async def send_telegram_buttons_async(
    message: str, buttons: list, topic: str | None = None
) -> int | None:
    """``send_telegram_buttons`` sem travar o event loop (precisa do message_id)."""
    return await asyncio.to_thread(send_telegram_buttons, message, buttons, topic)
