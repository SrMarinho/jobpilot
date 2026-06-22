"""LinkedIn checkpoint / CAPTCHA detection.

A scheduled run that lands on a security-verification page would otherwise
spin uselessly (no job cards, no buttons) or die with a confusing error. We
detect the checkpoint early, alert the human via Telegram ("resolve manual"),
and raise :class:`CheckpointError` so the caller aborts cleanly instead of
burning the run.

Detection is intentionally conservative — only fires on strong signals (URL
path + known verification markers) to avoid false positives that would block
healthy runs.
"""

from src.config.settings import logger

_URL_MARKERS = (
    "/checkpoint/challenge",
    "/checkpoint/lg/login-challenge",
    "/uas/consumer-email-challenge",
    "linkedin.com/checkpoint",
)

_TEXT_MARKERS = (
    "verificação de segurança",
    "verificacao de seguranca",
    "security verification",
    "vamos fazer uma verificação",
    "let's do a quick security check",
    "resolva este quebra-cabeça",
    "solve this puzzle",
    "prove que você é humano",
    "prove you're human",
    "we want to make sure it's really you",
    "queremos confirmar que é você",
    "i'm not a robot",
    "não sou um robô",
    "nao sou um robo",
)

# A genuine checkpoint shows almost no LinkedIn chrome; require a marker AND a
# short body to keep false positives near zero on normal pages that happen to
# mention "verification".
_MAX_CHECKPOINT_BODY = 4000


class CheckpointError(Exception):
    """Raised when LinkedIn presents a checkpoint/CAPTCHA needing human action."""


async def detect_checkpoint(page) -> str | None:
    """Return a short reason string if the page is a checkpoint, else None."""
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    for marker in _URL_MARKERS:
        if marker in url:
            return f"url:{marker}"

    # reCAPTCHA / hCaptcha iframes are a strong signal regardless of text.
    try:
        captcha = await page.query_selector(
            "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], "
            "iframe[title*='captcha' i], div.g-recaptcha"
        )
        if captcha:
            return "captcha:iframe"
    except Exception:
        pass

    try:
        body = (await page.evaluate("() => document.body.innerText || ''")).lower()
    except Exception:
        return None
    if len(body) > _MAX_CHECKPOINT_BODY:
        return None
    for marker in _TEXT_MARKERS:
        if marker in body:
            return f"text:{marker}"
    return None


async def ensure_not_blocked(page, label: str = "task") -> None:
    """Detect a checkpoint and, if present, alert Telegram + raise.

    Call after navigations that could redirect to verification. Best-effort:
    a detection failure (e.g. page closed) never masks the real work.
    """
    reason = await detect_checkpoint(page)
    if not reason:
        return
    logger.error(f"Checkpoint/CAPTCHA detected during {label}: {reason}")
    try:
        from src.utils.telegram import send_telegram

        send_telegram(
            "🚧 <b>Checkpoint do LinkedIn detectado!</b>\n"
            f"Tarefa: <code>{label}</code>\n"
            f"Motivo: <code>{reason}</code>\n\n"
            "Abra o Chrome e resolva a verificação manualmente. "
            "A automação foi interrompida para evitar bloqueio.",
            topic="alerts",
        )
    except Exception as e:
        logger.debug(f"Falha ao notificar checkpoint no Telegram: {e}")
    raise CheckpointError(reason)
