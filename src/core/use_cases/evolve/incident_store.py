"""Memória dos incidentes entre scans.

O ``log_scan`` é sem memória: relê a janela e reconta. Isso não basta pra um
sistema que decide sozinho, por dois motivos:

1. **Ruído tem que poder ser calado.** Sem isso o diagnóstico paga LLM toda
   noite pra reclassificar "Feed exhausted" — que é comportamento esperado.
2. **O que já foi tratado não pode voltar.** Um crônico que já virou patch
   (ou que a plataforma matou e nós aposentamos) continua aparecendo no log
   histórico; sem status persistido ele seria re-tratado pra sempre.

Estado por assinatura, não por ocorrência: o doc cresce com a variedade de
falhas (dezenas por mês), não com o volume (milhares). Um ``DocRepo``
single-doc dá conta e não precisa de DDL — o ``kv_store`` já existe nos dois
backends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from src.config.settings import files_dir
from src.core.persistence.doc_repo import DocRepo
from src.core.use_cases.evolve.log_scan import Incident

INCIDENTS_FILE = files_dir / "evolution_incidents.json"

# ``open`` é o único status que deixa o incidente ser tratado. Os outros são
# formas de "não mexa mais nisso", cada uma com um motivo diferente:
STATUS_OPEN = "open"
STATUS_IGNORED = "ignored"  # ruído — cala por um tempo
STATUS_RESOLVED = "resolved"  # já virou patch
STATUS_RETIRED = "retired"  # a plataforma matou a feature
STATUS_DEAD = "dead"  # tentamos e não deu; não insiste

SILENT_STATUSES = frozenset(
    {STATUS_IGNORED, STATUS_RESOLVED, STATUS_RETIRED, STATUS_DEAD}
)

DEFAULT_SUPPRESS_DAYS = 30


@dataclass(slots=True)
class IncidentState:
    """O que sabemos sobre uma assinatura além do que o log de hoje diz."""

    sig: str
    status: str = STATUS_OPEN
    suppress_until: str | None = None
    diagnosis: str | None = None
    note: str = ""
    attempts: int = 0
    first_recorded: str | None = None
    last_recorded: str | None = None
    template: str = ""

    def silenced(self, today: date | None = None) -> bool:
        if self.status in SILENT_STATUSES:
            if not self.suppress_until:
                return True
            # Supressão com prazo: passou o prazo, volta a ser tratável. Ruído
            # que voltou depois de um mês pode ter virado outra coisa.
            return (today or date.today()).isoformat() < self.suppress_until
        return False

    def as_doc(self) -> dict:
        return {
            "status": self.status,
            "suppress_until": self.suppress_until,
            "diagnosis": self.diagnosis,
            "note": self.note,
            "attempts": self.attempts,
            "first_recorded": self.first_recorded,
            "last_recorded": self.last_recorded,
            "template": self.template,
        }

    @classmethod
    def from_doc(cls, sig: str, doc: dict) -> IncidentState:
        return cls(
            sig=sig,
            status=doc.get("status", STATUS_OPEN),
            suppress_until=doc.get("suppress_until"),
            diagnosis=doc.get("diagnosis"),
            note=doc.get("note", ""),
            attempts=int(doc.get("attempts", 0) or 0),
            first_recorded=doc.get("first_recorded"),
            last_recorded=doc.get("last_recorded"),
            template=doc.get("template", ""),
        )


class IncidentStore:
    def __init__(self, repo: DocRepo | None = None):
        self._repo = repo or DocRepo("evolution_incidents", json_file=INCIDENTS_FILE)
        self._data = self._repo.load()
        self._data.setdefault("sigs", {})

    # ── leitura ─────────────────────────────────────────────────────────────
    def state(self, sig: str) -> IncidentState:
        return IncidentState.from_doc(sig, self._data["sigs"].get(sig, {}))

    def all_states(self) -> list[IncidentState]:
        return [
            IncidentState.from_doc(sig, doc)
            for sig, doc in sorted(self._data["sigs"].items())
        ]

    def actionable(
        self, incidents: list[Incident], *, today: date | None = None
    ) -> list[Incident]:
        """Só os incidentes que ainda podem ser tratados."""
        return [i for i in incidents if not self.state(i.sig).silenced(today)]

    # ── escrita ─────────────────────────────────────────────────────────────
    def record(self, incidents: list[Incident], *, now: datetime | None = None) -> int:
        """Registra as assinaturas vistas, preservando status já decidido.

        Devolve quantas assinaturas são novas. Não mexe em ``status``: a decisão
        é de quem diagnostica, não de quem observa.
        """
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        novos = 0
        for incident in incidents:
            doc = self._data["sigs"].get(incident.sig)
            if doc is None:
                doc = IncidentState(sig=incident.sig, first_recorded=stamp).as_doc()
                novos += 1
            doc["last_recorded"] = stamp
            # O template legível é atualizado sempre: se a mensagem mudou de
            # forma mas manteve a assinatura, o que vale é a redação atual.
            doc["template"] = incident.template
            self._data["sigs"][incident.sig] = doc
        if incidents:
            self._save()
        return novos

    def set_status(
        self,
        sig: str,
        status: str,
        *,
        suppress_days: int | None = None,
        diagnosis: str | None = None,
        note: str = "",
        today: date | None = None,
    ) -> IncidentState:
        state = self.state(sig)
        state.status = status
        if suppress_days is not None:
            state.suppress_until = (
                (today or date.today()) + timedelta(days=suppress_days)
            ).isoformat()
        if diagnosis is not None:
            state.diagnosis = diagnosis
        if note:
            state.note = note
        self._data["sigs"][sig] = state.as_doc()
        self._save()
        return state

    def ignore(self, sig: str, *, days: int = DEFAULT_SUPPRESS_DAYS, note: str = ""):
        return self.set_status(
            sig, STATUS_IGNORED, suppress_days=days, note=note or "ruído"
        )

    def bump_attempt(self, sig: str) -> int:
        state = self.state(sig)
        state.attempts += 1
        self._data["sigs"][sig] = state.as_doc()
        self._save()
        return state.attempts

    def _save(self) -> None:
        self._repo.save(self._data)


def load_incidents_store() -> IncidentStore:
    return IncidentStore()


# Caminho JSON usado pelo modo local; exposto pra quem precisa citar o arquivo.
def incidents_path() -> Path:
    return INCIDENTS_FILE
