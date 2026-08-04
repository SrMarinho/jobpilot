"""Vaga já avaliada pelo LLM — o veredito com a vaga a que se refere.

``EvalResult`` responde "essa vaga serve?"; aqui esse veredito ganha identidade
(qual vaga, quando, de que site) pra sobreviver ao fim do run.
"""

from dataclasses import dataclass
from datetime import datetime

from src.core.entities.eval_result import EvalResult

UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class EvaluatedJob:
    job_id: str
    title: str
    url: str
    evaluated_at: str
    company: str = ""
    site: str = UNKNOWN
    matches: bool = False
    salary: int | None = None
    contract: str = UNKNOWN
    reason: str = ""
    missing_skills: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        job_id: str,
        job_url: str,
        title: str,
        result: EvalResult,
        *,
        company: str = "",
        site: str = "",
    ) -> "EvaluatedJob":
        return cls(
            job_id=job_id,
            title=title,
            url=job_url,
            evaluated_at=datetime.now().isoformat(),
            company=company,
            site=site or UNKNOWN,
            matches=result.matches,
            salary=result.salary,
            contract=result.contract,
            reason=result.reason,
            missing_skills=tuple(result.missing_skills),
        )

    @classmethod
    def from_document(cls, job_id: str, doc: dict) -> "EvaluatedJob":
        return cls(
            job_id=job_id,
            title=doc.get("title", ""),
            url=doc.get("url", ""),
            evaluated_at=doc.get("evaluated_at", ""),
            company=doc.get("company", ""),
            site=doc.get("site", UNKNOWN),
            matches=bool(doc.get("matches")),
            salary=doc.get("salary"),
            contract=doc.get("contract", UNKNOWN),
            reason=doc.get("reason", ""),
            missing_skills=tuple(doc.get("missing_skills") or ()),
        )

    def as_result(self) -> EvalResult:
        """Volta pro veredito, pro apply reusar sem chamar o LLM de novo."""
        return EvalResult(
            matches=self.matches,
            salary=self.salary,
            reason=self.reason,
            missing_skills=list(self.missing_skills),
            contract=self.contract,
        )

    def as_record(self) -> dict:
        """Linha pro KeyedRepo — chaves = colunas de ``evaluated_jobs``."""
        return {
            "job_id": self.job_id,
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "site": self.site,
            "evaluated_at": self.evaluated_at,
            "matches": self.matches,
            "salary": self.salary,
            "contract": self.contract,
            "reason": self.reason,
            "missing_skills": list(self.missing_skills),
        }

    def as_document(self) -> dict:
        return {k: v for k, v in self.as_record().items() if k != "job_id"}

    @property
    def contract_tag(self) -> str:
        """Sufixo ` (CLT)` / ` (PJ)` — vazio quando desconhecido."""
        if not self.contract or self.contract == UNKNOWN:
            return ""
        return f" ({self.contract})"

    @property
    def score(self) -> int:
        """Ordenação da fila: salário estimado, 0 quando não deu match.

        Vaga rejeitada nunca sobe na lista, mesmo que o LLM tenha chutado um
        salário alto antes de reprovar por outro motivo.
        """
        if not self.matches:
            return 0
        return self.salary or 0
