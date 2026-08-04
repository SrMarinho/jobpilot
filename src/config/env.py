"""Leitura tipada de variáveis de ambiente.

``os.getenv`` devolve sempre string ou ``None``, então cada chamador refazia a
conversão à mão — ``int(os.getenv(...) or 12)``, ``os.getenv(...) == "1"``,
``os.getenv(...).upper() == "FALSE"`` — cada um com sua própria ideia do que
conta como verdadeiro e do que fazer com lixo. Aqui a conversão é uma só.

Leitura é sempre no momento da chamada, nunca no import: o bot e os comandos
ajustam ``os.environ`` em runtime (ex.: ``LLM_PROVIDER_EVAL``), e um valor
congelado no import ignoraria esse ajuste.
"""

import os

from src.config.settings import logger

TRUTHY = frozenset({"1", "true", "yes", "y", "on", "sim"})
FALSY = frozenset({"0", "false", "no", "n", "off", "nao", "não", ""})


def env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_int(name: str, default: int) -> int:
    """Inteiro da env; valor ilegível vira o default com aviso, não crash."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(f"{name}={raw!r} não é inteiro — usando {default}")
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUTHY:
        return True
    if normalized in FALSY:
        return False
    logger.warning(f"{name}={raw!r} não é booleano — usando {default}")
    return default


def env_required(name: str, *, hint: str = "") -> str:
    """Valor obrigatório. Ausente => erro claro no lugar de default silencioso."""
    value = env_str(name)
    if not value:
        suffix = f" {hint}" if hint else ""
        raise RuntimeError(f"{name} não configurado no .env.{suffix}")
    return value
