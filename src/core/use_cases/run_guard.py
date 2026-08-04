"""Decide se um run pode começar — o mesmo veredito pra CLI, bot e agendador.

Antes cada caminho tinha sua própria ideia disso: a CLI checava "já rodou hoje"
e "limite semanal" só quando recebia ``--scheduled``, e o bot não checava nada —
um ``/connect`` pelo Telegram furava a quota inteira.

As quatro barreiras, em ordem de severidade:

1. **Cooldown** (circuit breaker) — checkpoint ou falhas em sequência. Só sai
   por intervenção manual (`config limits --reset`).
2. **Janela horária** — atividade às 4h da manhã não parece humana.
3. **Quota** — teto proativo por dia/semana (:mod:`rate_limiter`).
4. **Já rodou hoje** — só para agendamento, evita repetir a cada logon.

``--force`` pula 2, 3 e 4. Nunca pula o cooldown: o breaker existe justamente
pros momentos em que insistir é o pior movimento.
"""

from dataclasses import dataclass
from datetime import datetime, time

from src.config.env import env_str
from src.config.settings import logger
from src.core.use_cases.rate_limiter import RateLimiter

#: Fora dessa janela os runs agendados não agem. Formato ``HH:MM-HH:MM``.
DEFAULT_ACTIVE_HOURS = "07:00-23:00"


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def _parse_window(raw: str) -> tuple[time, time] | None:
    try:
        start_raw, end_raw = raw.split("-")
        start = time.fromisoformat(start_raw.strip())
        end = time.fromisoformat(end_raw.strip())
        return start, end
    except Exception:
        logger.warning(f"ACTIVE_HOURS={raw!r} inválido — janela horária ignorada")
        return None


def within_active_hours(now: datetime | None = None) -> bool:
    """``True`` se o horário atual está dentro de ``ACTIVE_HOURS``."""
    window = _parse_window(env_str("ACTIVE_HOURS", DEFAULT_ACTIVE_HOURS))
    if window is None:
        return True
    start, end = window
    current = (now or datetime.now()).time()
    if start <= end:
        return start <= current <= end
    # Janela que cruza a meia-noite (ex.: 22:00-06:00).
    return current >= start or current <= end


def check_run(
    action: str,
    *,
    scheduled: bool = False,
    force: bool = False,
    limiter: RateLimiter | None = None,
    now: datetime | None = None,
) -> GuardVerdict:
    """Veredito único sobre iniciar um run de ``action``.

    ``scheduled`` liga as barreiras de janela horária e "já rodou hoje";
    ``force`` desliga tudo menos o cooldown.
    """
    limiter = limiter or RateLimiter()

    cooldown = limiter.cooldown_reason()
    if cooldown:
        return GuardVerdict(False, f"em cooldown: {cooldown}")

    if force:
        return GuardVerdict(True)

    if scheduled and not within_active_hours(now):
        janela = env_str("ACTIVE_HOURS", DEFAULT_ACTIVE_HOURS)
        return GuardVerdict(False, f"fora da janela de atividade ({janela})")

    quota = limiter.check(action)
    if not quota:
        return GuardVerdict(False, quota.reason)

    if scheduled:
        from src.interfaces.cli.persistence import (
            is_already_ran_today,
            is_weekly_limit_reached,
        )

        if is_already_ran_today(action):
            return GuardVerdict(False, f"{action} já rodou hoje")
        if is_weekly_limit_reached(action):
            return GuardVerdict(False, f"limite semanal de {action} já sinalizado")

    return GuardVerdict(True)
