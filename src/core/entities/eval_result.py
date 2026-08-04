"""Resultado da avaliação de uma vaga pelo LLM."""

from dataclasses import dataclass, field

UNKNOWN_CONTRACT = "unknown"


@dataclass(frozen=True, slots=True)
class EvalResult:
    """Veredito do LLM sobre uma vaga.

    ``matches`` decide se a candidatura segue; ``salary`` é a pretensão a
    preencher no formulário; ``missing_skills`` alimenta o skills tracker.
    """

    matches: bool = False
    salary: int | None = None
    reason: str = ""
    missing_skills: list[str] = field(default_factory=list)
    contract: str = UNKNOWN_CONTRACT

    @classmethod
    def parse_error(cls) -> "EvalResult":
        """Fallback quando a linha do LLM não pôde ser interpretada."""
        return cls(reason="parse error")

    @property
    def contract_tag(self) -> str:
        """Sufixo ` (CLT)` / ` (PJ)` — vazio quando o contrato é desconhecido."""
        if not self.contract or self.contract == UNKNOWN_CONTRACT:
            return ""
        return f" ({self.contract})"

    def summary(self) -> str:
        """Linha única pro log."""
        verdict = "YES" if self.matches else "NO"
        missing = f" | missing: {self.missing_skills}" if self.missing_skills else ""
        return (
            f"{verdict} | salary={self.salary} | contract={self.contract} "
            f"| {self.reason}{missing}"
        )
