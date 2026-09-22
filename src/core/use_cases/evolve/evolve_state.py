"""Contadores e freios do patch autônomo.

Separado do ``RateLimiter`` de propósito. O limiter existente é sobre o que o
LinkedIn tolera, e o cooldown dele **bloqueia todos os runs agendados por 24h**
— usá-lo aqui faria uma falha de patch parar as candidaturas, que é o oposto do
objetivo. Aqui o cooldown só para a evolução.

O que mora aqui e por quê:

- ``patches`` por dia e por semana — teto de gasto de LLM.
- ``usd`` do dia, somado do JSON que o ``claude -p`` devolve. É o único freio
  que enxerga custo de verdade, e não número de chamadas.
- ``consecutive_failures`` — três falhas de gate **seguidas, entre jobs
  diferentes**, indicam que algo sistêmico quebrou (suíte vermelha na master,
  CLI que não importa). Nesse caso insistir só produz branches inúteis.
- ``paused`` — kill switch que não exige mexer no ``.env``, para o dono poder
  desligar do celular via bot.
- ``attempted`` — pares ``(assinatura, commit base)`` já tentados. É o
  anti-loop: um mesmo problema sobre um mesmo código é tentado **uma** vez,
  para sempre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config.settings import files_dir
from src.core.persistence.doc_repo import DocRepo
from src.core.use_cases.evolve.patch_policy import COOLDOWN_HOURS

EVOLVE_STATE_FILE = files_dir / "evolution_state.json"

#: Dias de contador guardados. Sem poda o doc cresce pra sempre.
_KEEP_DAYS = 60
#: Tentativas guardadas no anti-loop.
_KEEP_ATTEMPTS = 200


def _week_key(day: date) -> str:
    return day.strftime("%Y-W%W")


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Tudo que ``check_budget`` precisa, num objeto só."""

    patches_today: int
    patches_week: int
    usd_today: float
    paused: bool
    in_cooldown: bool
    cooldown_until: str | None
    consecutive_failures: int


class EvolveState:
    def __init__(self, repo: DocRepo | None = None, today: date | None = None):
        self._repo = repo or DocRepo("evolution_state", json_file=EVOLVE_STATE_FILE)
        self._today = today or date.today()
        self._data = self._repo.load()
        self._data.setdefault("patches", {})
        self._data.setdefault("usd", {})
        self._data.setdefault("attempted", [])
        self._data.setdefault("consecutive_failures", 0)
        self._data.setdefault("paused", False)
        self._data.setdefault("cooldown_until", None)

    # ── leitura ─────────────────────────────────────────────────────────────
    @property
    def paused(self) -> bool:
        return bool(self._data.get("paused", False))

    def patches_today(self) -> int:
        return int(self._data["patches"].get(self._today.isoformat(), 0) or 0)

    def patches_this_week(self) -> int:
        semana = _week_key(self._today)
        total = 0
        for dia, quantos in self._data["patches"].items():
            try:
                if _week_key(date.fromisoformat(dia)) == semana:
                    total += int(quantos or 0)
            except ValueError:
                continue
        return total

    def usd_today(self) -> float:
        return float(self._data["usd"].get(self._today.isoformat(), 0.0) or 0.0)

    def in_cooldown(self, *, now: datetime | None = None) -> bool:
        raw = self._data.get("cooldown_until")
        if not raw:
            return False
        try:
            return (now or datetime.now()) < datetime.fromisoformat(raw)
        except ValueError:
            # Valor corrompido não pode travar a evolução pra sempre.
            return False

    def snapshot(self, *, now: datetime | None = None) -> Snapshot:
        return Snapshot(
            patches_today=self.patches_today(),
            patches_week=self.patches_this_week(),
            usd_today=self.usd_today(),
            paused=self.paused,
            in_cooldown=self.in_cooldown(now=now),
            cooldown_until=self._data.get("cooldown_until"),
            consecutive_failures=int(self._data.get("consecutive_failures", 0) or 0),
        )

    def already_attempted(self, sig: str | None, base_sha: str | None) -> bool:
        """Esse problema já foi tentado sobre esse mesmo código?"""
        if not sig or not base_sha:
            return False
        return f"{sig}|{base_sha}" in set(self._data["attempted"])

    # ── escrita ─────────────────────────────────────────────────────────────
    def record_attempt(self, sig: str | None, base_sha: str | None) -> None:
        if not sig or not base_sha:
            return
        chave = f"{sig}|{base_sha}"
        if chave not in self._data["attempted"]:
            self._data["attempted"].append(chave)
            self._data["attempted"] = self._data["attempted"][-_KEEP_ATTEMPTS:]
            self._save()

    def record_patch(self, *, usd: float = 0.0) -> None:
        """Um patch consumido — contado mesmo quando os gates reprovam.

        O custo do LLM já aconteceu; contar só o sucesso deixaria o teto diário
        ser furado por uma sequência de tentativas falhas.
        """
        chave = self._today.isoformat()
        self._data["patches"][chave] = self.patches_today() + 1
        if usd:
            self._data["usd"][chave] = round(self.usd_today() + usd, 4)
        self._prune()
        self._save()

    def record_gate_failure(self, *, now: datetime | None = None) -> int:
        """Falha de gate. Abre o cooldown ao bater o limite."""
        from src.core.use_cases.evolve.patch_policy import GLOBAL_FAILURE_THRESHOLD

        atual = int(self._data.get("consecutive_failures", 0) or 0) + 1
        self._data["consecutive_failures"] = atual
        if atual >= GLOBAL_FAILURE_THRESHOLD:
            until = (now or datetime.now()) + timedelta(hours=COOLDOWN_HOURS)
            self._data["cooldown_until"] = until.isoformat(timespec="seconds")
        self._save()
        return atual

    def record_gate_success(self) -> None:
        self._data["consecutive_failures"] = 0
        self._data["cooldown_until"] = None
        self._save()

    def pause(self, paused: bool = True) -> None:
        self._data["paused"] = paused
        self._save()

    def clear_cooldown(self) -> None:
        self._data["cooldown_until"] = None
        self._data["consecutive_failures"] = 0
        self._save()

    def _prune(self) -> None:
        for chave in ("patches", "usd"):
            dados = self._data[chave]
            if len(dados) > _KEEP_DAYS:
                for dia in sorted(dados)[: len(dados) - _KEEP_DAYS]:
                    dados.pop(dia, None)

    def _save(self) -> None:
        self._repo.save(self._data)


def state_path() -> Path:
    return EVOLVE_STATE_FILE
