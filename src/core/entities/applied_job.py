"""Registro de candidatura enviada e de vaga rejeitada.

Os campos espelham 1:1 as colunas de ``applied_jobs`` / ``rejected_jobs`` no
DDL de ``src/core/persistence/db.py`` — ``as_record()`` é o único lugar que
conhece esse mapeamento, então uma coluna nova se adiciona aqui e no DDL, não
espalhada por chamadores montando dict à mão.
"""

from dataclasses import dataclass
from datetime import datetime

UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AppliedJob:
    job_id: str
    title: str
    url: str
    applied_at: str
    company: str = ""
    salary_offered: int | None = None
    level: str = UNKNOWN
    site: str = UNKNOWN
    contract: str = UNKNOWN

    @classmethod
    def create(
        cls,
        job_id: str,
        job_url: str,
        title: str,
        *,
        salary: int | None = None,
        company: str = "",
        level: str = "",
        site: str = "",
        contract: str = "",
    ) -> "AppliedJob":
        return cls(
            job_id=job_id,
            title=title,
            url=job_url,
            applied_at=datetime.now().isoformat(),
            company=company,
            salary_offered=salary,
            level=level or UNKNOWN,
            site=site or UNKNOWN,
            contract=contract or UNKNOWN,
        )

    def as_record(self) -> dict:
        """Linha pro KeyedRepo — chaves = colunas da tabela ``applied_jobs``."""
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "applied_at": self.applied_at,
            "salary_offered": self.salary_offered,
            "level": self.level,
            "site": self.site,
            "contract": self.contract,
        }

    def as_document(self) -> dict:
        """Valor pro JSON local — igual ao record, sem a chave primária."""
        return {k: v for k, v in self.as_record().items() if k != "job_id"}


@dataclass(frozen=True, slots=True)
class RejectedJob:
    job_id: str
    title: str
    url: str
    rejected_at: str
    reason: str = ""
    site: str = UNKNOWN

    @classmethod
    def create(
        cls, job_id: str, job_url: str, title: str, *, reason: str = "", site: str = ""
    ) -> "RejectedJob":
        return cls(
            job_id=job_id,
            title=title,
            url=job_url,
            rejected_at=datetime.now().isoformat(),
            reason=reason,
            site=site or UNKNOWN,
        )

    def as_record(self) -> dict:
        """Linha pro KeyedRepo — chaves = colunas da tabela ``rejected_jobs``."""
        return {
            "job_id": self.job_id,
            "title": self.title,
            "url": self.url,
            "rejected_at": self.rejected_at,
            "reason": self.reason,
            "site": self.site,
        }

    def as_document(self) -> dict:
        return {k: v for k, v in self.as_record().items() if k != "job_id"}
