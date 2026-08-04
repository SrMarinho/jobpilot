"""Tabela de referência salarial BRL usada no prompt de avaliação.

Estava hardcoded duas vezes dentro do ``job_evaluator`` (uma no prompt single,
outra no batch), então ajustar a faixa exigia editar os dois e torcer pra não
divergirem. Aqui é dado, não texto de prompt: o bloco enviado ao LLM é
renderizado a partir da tabela.
"""

from dataclasses import dataclass

CONTRACTS = ("CLT", "PJ")


@dataclass(frozen=True, slots=True)
class SalaryBand:
    level: str
    clt: tuple[int, int]
    pj: tuple[int, int]

    def as_line(self) -> str:
        return (
            f"- {self.level.capitalize():<6} CLT {self.clt[0]}-{self.clt[1]} "
            f"| {self.level.capitalize()} PJ {self.pj[0]}-{self.pj[1]}"
        )


SALARY_BANDS: tuple[SalaryBand, ...] = (
    SalaryBand("junior", clt=(3000, 6000), pj=(4000, 8000)),
    SalaryBand("pleno", clt=(6000, 10000), pj=(8000, 14000)),
    SalaryBand("senior", clt=(10000, 18000), pj=(14000, 25000)),
)


def salary_reference_block() -> str:
    """Bloco pronto pra interpolar no prompt."""
    lines = "\n".join(band.as_line() for band in SALARY_BANDS)
    return f"Salary reference (BRL/month):\n{lines}"
