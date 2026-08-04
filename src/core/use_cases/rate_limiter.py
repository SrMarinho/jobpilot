"""Quotas proativas por ação, contadas antes de agir.

O controle antigo era **reativo**: o app só sabia que tinha estourado o limite
depois que o LinkedIn mostrava o modal de "fuse limit" — ou seja, depois de já
ter batido no teto e chamado atenção. E o guard só rodava com ``--scheduled``,
então uma execução manual ou pelo bot passava direto.

Aqui a contagem é do próprio app: cada ação enviada é registrada, e o manager
pergunta ``allows()`` **antes** de agir. Quando o teto chega, o run para sozinho
com motivo claro em vez de insistir.

Também guarda o cooldown do circuit breaker: um checkpoint do LinkedIn ou uma
sequência de falhas bloqueia os runs agendados até intervenção manual.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from src.config.env import env_int
from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo

RATE_LIMITS_FILE = files_dir / "rate_limits.json"

#: Falhas consecutivas que disparam o cooldown.
FAILURE_THRESHOLD = 5
#: Quanto tempo os runs agendados ficam bloqueados após o breaker abrir.
COOLDOWN_HOURS = 24


@dataclass(frozen=True, slots=True)
class Quota:
    """Teto de uma ação. ``0`` desliga o limite naquela janela."""

    action: str
    per_day: int
    per_week: int

    @classmethod
    def from_env(cls, action: str, per_day: int, per_week: int) -> "Quota":
        """Teto configurável por env: ``LIMIT_CONNECT_DAY``, ``LIMIT_CONNECT_WEEK``…"""
        key = action.upper()
        return cls(
            action=action,
            per_day=env_int(f"LIMIT_{key}_DAY", per_day),
            per_week=env_int(f"LIMIT_{key}_WEEK", per_week),
        )


# Padrões conservadores. O LinkedIn não publica os limites reais; estes ficam
# bem abaixo do que costuma disparar restrição, e são ajustáveis por env.
DEFAULT_QUOTAS: dict[str, tuple[int, int]] = {
    "connect": (25, 100),
    "apply": (30, 150),
    "engage": (20, 100),
    "dm": (15, 60),
}


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    """Resposta de ``check()`` — inclui o porquê, pra virar log e mensagem."""

    allowed: bool
    action: str
    reason: str = ""
    used_today: int = 0
    used_week: int = 0

    def __bool__(self) -> bool:
        return self.allowed


def _week_key(day: date) -> str:
    return day.strftime("%Y-W%W")


class RateLimiter:
    def __init__(self, repo: DocRepo | None = None, today: date | None = None):
        self._repo = repo or DocRepo("rate_limits", json_file=RATE_LIMITS_FILE)
        self._today = today or date.today()
        self._data = self._repo.load()

    # ── Contagem ─────────────────────────────────────────────────────────────

    def _counts(self) -> dict:
        return self._data.setdefault("counts", {})

    def used_today(self, action: str) -> int:
        return self._counts().get(action, {}).get(self._today.isoformat(), 0)

    def used_this_week(self, action: str) -> int:
        """Soma os dias da semana corrente (segunda a domingo)."""
        by_day = self._counts().get(action, {})
        week = _week_key(self._today)
        return sum(count for day, count in by_day.items() if _safe_week(day) == week)

    def quota(self, action: str) -> Quota:
        per_day, per_week = DEFAULT_QUOTAS.get(action, (0, 0))
        return Quota.from_env(action, per_day, per_week)

    # ── Decisão ──────────────────────────────────────────────────────────────

    def check(self, action: str) -> QuotaStatus:
        """Pode executar mais uma ação dessas agora?"""
        quota = self.quota(action)
        used_today = self.used_today(action)
        used_week = self.used_this_week(action)

        if quota.per_day and used_today >= quota.per_day:
            return QuotaStatus(
                False,
                action,
                f"limite diário de {action} atingido ({used_today}/{quota.per_day})",
                used_today,
                used_week,
            )
        if quota.per_week and used_week >= quota.per_week:
            return QuotaStatus(
                False,
                action,
                f"limite semanal de {action} atingido ({used_week}/{quota.per_week})",
                used_today,
                used_week,
            )
        return QuotaStatus(True, action, "", used_today, used_week)

    def allows(self, action: str) -> bool:
        return bool(self.check(action))

    def remaining_today(self, action: str) -> int:
        quota = self.quota(action)
        if not quota.per_day:
            return -1  # sem teto
        return max(0, quota.per_day - self.used_today(action))

    # ── Registro ─────────────────────────────────────────────────────────────

    def record(self, action: str, amount: int = 1) -> None:
        """Contabiliza ações já executadas."""
        by_day = self._counts().setdefault(action, {})
        key = self._today.isoformat()
        by_day[key] = by_day.get(key, 0) + amount
        self._prune(by_day)
        self._save()

    @staticmethod
    def _prune(by_day: dict, keep_days: int = 60) -> None:
        """Descarta dias velhos — o arquivo cresceria pra sempre sem isso."""
        if len(by_day) <= keep_days:
            return
        for old in sorted(by_day)[:-keep_days]:
            by_day.pop(old, None)

    # ── Circuit breaker ──────────────────────────────────────────────────────

    def record_failure(self, action: str, reason: str = "") -> bool:
        """Conta uma falha. Devolve ``True`` se abriu o cooldown."""
        failures = self._data.setdefault("failures", {})
        failures[action] = failures.get(action, 0) + 1
        if failures[action] >= FAILURE_THRESHOLD:
            self.open_cooldown(
                f"{failures[action]} falhas seguidas em {action}: {reason}"
            )
            failures[action] = 0
            self._save()
            return True
        self._save()
        return False

    def record_success(self, action: str) -> None:
        """Zera o contador — o breaker só liga em falha *consecutiva*."""
        failures = self._data.setdefault("failures", {})
        if failures.get(action):
            failures[action] = 0
            self._save()

    def open_cooldown(self, reason: str, hours: int = COOLDOWN_HOURS) -> None:
        until = datetime.now() + timedelta(hours=hours)
        self._data["cooldown"] = {"until": until.isoformat(), "reason": reason}
        logger.error(f"Circuit breaker aberto até {until:%d/%m %H:%M} — {reason}")
        self._save()

    def clear_cooldown(self) -> None:
        self._data.pop("cooldown", None)
        self._data["failures"] = {}
        self._save()

    def cooldown_reason(self) -> str | None:
        """Motivo do bloqueio, ou ``None`` se está liberado."""
        cooldown = self._data.get("cooldown")
        if not cooldown:
            return None
        try:
            until = datetime.fromisoformat(cooldown["until"])
        except Exception:
            self._data.pop("cooldown", None)
            return None
        if datetime.now() >= until:
            self.clear_cooldown()
            return None
        return (
            f"{cooldown.get('reason', 'motivo desconhecido')} (até {until:%d/%m %H:%M})"
        )

    # ── Persistência ─────────────────────────────────────────────────────────

    def _save(self) -> None:
        self._repo.save(self._data)


def _safe_week(day_iso: str) -> str:
    try:
        return _week_key(date.fromisoformat(day_iso))
    except Exception:
        return ""
