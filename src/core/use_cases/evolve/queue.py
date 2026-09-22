"""Fila de trabalho da autoevolução.

A cura acontece dentro do run, com o browser na mão. O que vem depois dela —
promover o selector pro código-fonte, rodar ruff/pytest, abrir branch — não
pode acontecer ali: leva minutos, não precisa de browser, e seguraria o lock
que outros runs estão esperando.

Então a cura **enfileira** e o drain horário **executa**. É o desacoplamento
que já existe no autopost (gera → aprova → publica), aplicado ao patch.

Fila separada do store de incidentes de propósito: incidente é observação, job
é intenção. Um incidente gera zero ou vários jobs, e a fila precisa esvaziar
sem apagar o histórico de incidentes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo

QUEUE_FILE = files_dir / "evolution_queue.json"

# Tipos de job. Só o primeiro é edição mecânica; os outros precisam de LLM
# escrevendo código, e por isso passam por gates mais caros.
KIND_PROMOTE_SELECTOR = "promote_selector"
KIND_RETIRE_FEATURE = "retire_feature"
KIND_PATCH_BUG = "patch_bug"
KIND_DEMOTE_LOG = "demote_log"

KINDS = frozenset(
    {KIND_PROMOTE_SELECTOR, KIND_RETIRE_FEATURE, KIND_PATCH_BUG, KIND_DEMOTE_LOG}
)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DEAD = "dead"

#: Duas falhas no mesmo job e ele morre. Um job que não passa nos gates não vai
#: passar na terceira: insistir é queimar LLM e poluir o histórico de branches.
MAX_ATTEMPTS = 2

#: Teto do histórico no doc. O detalhe de cada tentativa vive em
#: `evolution_patches/<id>`; aqui fica só o suficiente pra não repetir trabalho.
_KEEP_FINISHED = 50


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    payload: dict = field(default_factory=dict)
    status: str = STATUS_PENDING
    attempts: int = 0
    created_at: str = ""
    updated_at: str = ""
    last_error: str = ""
    # Assinatura do incidente que originou o job, quando houver. É o que
    # permite marcar o incidente como resolvido quando o patch entra.
    sig: str | None = None
    # Comit base da tentativa. Junto com `sig` forma a chave anti-loop: um
    # mesmo problema sobre um mesmo código só é tentado uma vez.
    base_sha: str | None = None

    @property
    def dedupe_key(self) -> str:
        """Identidade lógica do job, para não enfileirar o mesmo duas vezes."""
        if self.kind == KIND_PROMOTE_SELECTOR:
            return f"{self.kind}|{self.payload.get('field')}|{self.payload.get('selector')}"
        return f"{self.kind}|{self.sig or self.payload.get('field') or self.id}"

    @property
    def finished(self) -> bool:
        return self.status in {STATUS_DONE, STATUS_DEAD}

    def as_doc(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "payload": self.payload,
            "status": self.status,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_error": self.last_error,
            "sig": self.sig,
            "base_sha": self.base_sha,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> Job:
        return cls(
            id=doc["id"],
            kind=doc.get("kind", ""),
            payload=doc.get("payload", {}) or {},
            status=doc.get("status", STATUS_PENDING),
            attempts=int(doc.get("attempts", 0) or 0),
            created_at=doc.get("created_at", ""),
            updated_at=doc.get("updated_at", ""),
            last_error=doc.get("last_error", ""),
            sig=doc.get("sig"),
            base_sha=doc.get("base_sha"),
        )


class EvolutionQueue:
    def __init__(self, repo: DocRepo | None = None):
        self._repo = repo or DocRepo("evolution_queue", json_file=QUEUE_FILE)
        self._data = self._repo.load()
        self._data.setdefault("jobs", [])

    # ── leitura ─────────────────────────────────────────────────────────────
    def all(self) -> list[Job]:
        return [Job.from_doc(d) for d in self._data["jobs"]]

    def pending(self) -> list[Job]:
        return [j for j in self.all() if j.status in {STATUS_PENDING, STATUS_FAILED}]

    def next_job(self) -> Job | None:
        """Próximo job a executar, ou ``None``.

        Um por drain: o drain tem teto de tempo no Agendador, e um patch pode
        levar minutos entre LLM, pytest e smoke.
        """
        for job in self.pending():
            if job.attempts < MAX_ATTEMPTS:
                return job
        return None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for job in self.all():
            out[job.status] = out.get(job.status, 0) + 1
        return out

    # ── escrita ─────────────────────────────────────────────────────────────
    def enqueue(
        self,
        kind: str,
        payload: dict,
        *,
        sig: str | None = None,
        now: datetime | None = None,
    ) -> Job | None:
        """Enfileira. ``None`` quando já existe job equivalente não terminado.

        Dedupe pela identidade lógica, não pelo id: sem isso, uma cura que
        acontece em três runs seguidos abriria três branches pro mesmo
        selector.
        """
        if kind not in KINDS:
            raise ValueError(f"tipo de job desconhecido: {kind}")

        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            payload=payload,
            sig=sig,
            created_at=stamp,
            updated_at=stamp,
        )

        for existing in self.all():
            if existing.dedupe_key == job.dedupe_key and not existing.finished:
                logger.info(
                    f"[evolve] job já na fila ({existing.dedupe_key}) — não duplica"
                )
                return None
            if existing.dedupe_key == job.dedupe_key and existing.status == STATUS_DONE:
                logger.info(
                    f"[evolve] job já concluído antes ({existing.dedupe_key}) — ignora"
                )
                return None

        self._data["jobs"].append(job.as_doc())
        self._save()
        logger.info(f"[evolve] job enfileirado: {kind} ({job.id})")
        return job

    def mark_running(self, job_id: str, *, base_sha: str | None = None) -> None:
        self._update(job_id, status=STATUS_RUNNING, base_sha=base_sha, bump=True)

    def mark_done(self, job_id: str, *, note: str = "") -> None:
        self._update(job_id, status=STATUS_DONE, last_error=note)

    def mark_failed(self, job_id: str, error: str) -> Job | None:
        """Falha. Vira ``dead`` quando esgota as tentativas."""
        job = self.get(job_id)
        if job is None:
            return None
        status = STATUS_DEAD if job.attempts >= MAX_ATTEMPTS else STATUS_FAILED
        if status == STATUS_DEAD:
            logger.warning(
                f"[evolve] job {job_id} morto após {job.attempts} tentativa(s): "
                f"{error[:120]}"
            )
        self._update(job_id, status=status, last_error=error[:500])
        return self.get(job_id)

    def get(self, job_id: str) -> Job | None:
        for doc in self._data["jobs"]:
            if doc["id"] == job_id:
                return Job.from_doc(doc)
        return None

    def purge_finished(self, keep: int = _KEEP_FINISHED) -> int:
        """Descarta jobs terminados antigos, mantendo os ``keep`` últimos.

        Mantém a ordem e nunca toca em job pendente — o histórico serve pro
        dedupe ("esse selector já foi promovido"), então descartar demais faria
        o mesmo trabalho voltar.
        """
        indices_terminados = [
            i for i, d in enumerate(self._data["jobs"]) if Job.from_doc(d).finished
        ]
        if len(indices_terminados) <= keep:
            return 0
        descartar = set(indices_terminados[: len(indices_terminados) - keep])
        self._data["jobs"] = [
            d for i, d in enumerate(self._data["jobs"]) if i not in descartar
        ]
        self._save()
        return len(descartar)

    def _update(self, job_id: str, *, bump: bool = False, **fields) -> None:
        for doc in self._data["jobs"]:
            if doc["id"] != job_id:
                continue
            for chave, valor in fields.items():
                if valor is not None:
                    doc[chave] = valor
            if bump:
                doc["attempts"] = int(doc.get("attempts", 0) or 0) + 1
            doc["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self._save()
            return

    def _save(self) -> None:
        self._repo.save(self._data)


def queue_path() -> Path:
    return QUEUE_FILE
