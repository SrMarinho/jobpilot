"""Histórico das avaliações do LLM — o que antes era descartado.

Cada vaga custa uma chamada de LLM pra ser avaliada, e o veredito morria no fim
do run: a mesma vaga reaparecendo numa busca amanhã era reavaliada do zero, e
tudo que foi aprovado mas não deu pra aplicar (limite batido, formulário
travado) sumia sem deixar rastro.

Guardando, três coisas passam a existir: fila de vagas aprovadas em aberto,
cache de avaliação (mesma vaga não gasta token duas vezes) e a base do funil
`visto → avaliado → aplicado`.
"""

import json
from datetime import date, datetime, timedelta

from src.config.settings import files_dir, logger
from src.core.entities.eval_result import EvalResult
from src.core.entities.evaluated_job import EvaluatedJob
from src.core.persistence.db import is_db_enabled
from src.core.persistence.keyed_repo import KeyedRepo

EVALUATED_JOBS_FILE = files_dir / "evaluated_jobs.json"

#: Uma avaliação velha não vale reuso — a vaga pode ter mudado ou fechado.
DEFAULT_TTL_DAYS = 30


class EvaluatedJobsTracker:
    def __init__(self, path=EVALUATED_JOBS_FILE, ttl_days: int = DEFAULT_TTL_DAYS):
        self._path = path
        self._ttl_days = ttl_days
        self._repo = KeyedRepo("evaluated_jobs", "job_id")
        self._data: dict = self._load()

    # ── Persistência ─────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if is_db_enabled():
            return {
                row["job_id"]: {k: v for k, v in row.items() if k != "job_id"}
                for row in self._repo.all()
            }
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, starting fresh")
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def save(self, job: EvaluatedJob) -> None:
        self._data[job.job_id] = job.as_document()
        if is_db_enabled():
            self._repo.upsert(job.as_record())
        else:
            self._save()

    # ── Leitura ──────────────────────────────────────────────────────────────

    def get(self, job_id: str) -> EvaluatedJob | None:
        doc = self._data.get(job_id)
        if not doc:
            return None
        return EvaluatedJob.from_document(job_id, doc)

    def cached_result(self, job_id: str) -> EvalResult | None:
        """Veredito reaproveitável, ou ``None`` se ausente/vencido.

        É o que evita gastar token reavaliando a mesma vaga que reaparece na
        busca do dia seguinte.
        """
        job = self.get(job_id)
        if job is None:
            return None
        if self._is_stale(job):
            return None
        return job.as_result()

    def _is_stale(self, job: EvaluatedJob) -> bool:
        try:
            evaluated = datetime.fromisoformat(job.evaluated_at).date()
        except Exception:
            return True
        return (date.today() - evaluated) > timedelta(days=self._ttl_days)

    def all_jobs(self) -> list[EvaluatedJob]:
        return [EvaluatedJob.from_document(jid, doc) for jid, doc in self._data.items()]

    def queue(
        self, applied_ids: set[str] | None = None, limit: int = 0
    ) -> list[EvaluatedJob]:
        """Aprovadas que ainda não viraram candidatura, da melhor pra pior."""
        applied_ids = applied_ids or set()
        pending = [
            job
            for job in self.all_jobs()
            if job.matches and job.job_id not in applied_ids
        ]
        pending.sort(key=lambda j: (j.score, j.evaluated_at), reverse=True)
        return pending[:limit] if limit else pending

    def stats(self) -> dict:
        """Contagens do funil na etapa de avaliação."""
        jobs = self.all_jobs()
        aprovadas = [j for j in jobs if j.matches]
        return {
            "evaluated": len(jobs),
            "approved": len(aprovadas),
            "rejected": len(jobs) - len(aprovadas),
            "avg_salary": (
                round(sum(j.salary for j in aprovadas if j.salary) / len(aprovadas))
                if aprovadas
                else 0
            ),
        }
