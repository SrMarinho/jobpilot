import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

# ── global run context ──────────────────────────────────────────────────────
_RUN_CTX: dict = {"id": "-", "type": "-"}


def set_run_context(run_type: str = ""):
    _RUN_CTX["id"] = uuid.uuid4().hex[:8]
    _RUN_CTX["type"] = run_type


class RunContextFilter(logging.Filter):
    """Injects run_id / run_type into every log record. Defaults to '-' when unset."""

    def filter(self, record):
        record.run_id = _RUN_CTX.get("id", "-")
        record.run_type = _RUN_CTX.get("type", "-")
        return True


# Token do bot do Telegram (``<id numérico>:<35 chars>``). Aparece sempre que
# uma exceção do requests inclui a URL da Bot API — e a URL carrega o token.
# Mascarar na saída do formatter cobre qualquer caminho de log, inclusive
# traceback, sem depender de cada call site lembrar de limpar. Sem ``\b`` na
# frente: na URL o token vem colado em "bot" (``/bot123:AA…``), e entre "t" e
# "1" não há fronteira de palavra.
_TELEGRAM_TOKEN_RE = re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}")


def redact_secrets(text: str) -> str:
    return _TELEGRAM_TOKEN_RE.sub("<telegram-token>", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        return redact_secrets(super().format(record))


# -------------------------------------------------------------
# Formatter opcional — elimina quebras de linha nos logs
# -------------------------------------------------------------
class SingleLineFormatter(RedactingFormatter):
    def format(self, record):
        msg = super().format(record)
        return msg.replace("\n", " ")


# -------------------------------------------------------------
# Wrapper / fábrica de logger
# -------------------------------------------------------------
class CustomLogger:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.logger = self._configure()

    # público ────────────────────────────────────────────────
    def get_logger(self) -> logging.Logger:
        """Retorna o logger pronto para usar."""
        return self.logger

    # privado ────────────────────────────────────────────────
    def _configure(self) -> logging.Logger:
        logger = logging.getLogger(self.cfg["app_name"])

        # Se já tem handlers, alguém já configurou — só devolve
        if logger.handlers:
            return logger

        run_filter = RunContextFilter()
        logger.addFilter(run_filter)

        logger.setLevel(getattr(logging, self.cfg["log_level"].upper(), logging.INFO))

        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(
            SingleLineFormatter("[%(run_id)s] [%(run_type)s] %(message)s")
        )
        console.addFilter(run_filter)
        logger.addHandler(console)

        file_path = self._build_log_path(self.cfg["log_dir"])
        file_handler = logging.FileHandler(file_path, mode="a", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            RedactingFormatter(
                "%(asctime)s - [%(run_id)s] - [%(run_type)s] - %(levelname)s - %(message)s"
            )
        )
        file_handler.addFilter(run_filter)
        logger.addHandler(file_handler)

        return logger

    @staticmethod
    def _build_log_path(base_dir: Path) -> Path:
        """Garante a pasta …/<ano>/<mês>/ e devolve o caminho do log YYYYMMDD.log."""
        today = datetime.now()
        folder = base_dir / f"{today:%Y}" / f"{today:%m}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / f"{today:%Y%m%d}.log"
