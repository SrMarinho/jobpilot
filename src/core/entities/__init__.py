"""Entidades de domínio — os objetos que atravessam as camadas.

Antes o domínio trafegava como `dict` solto e tupla posicional: a avaliação de
uma vaga era uma `tuple[bool, int|None, str, list[str], str]` que os chamadores
indexavam por número (`item.eval_result[4]`), e a candidatura era um dict cujas
chaves precisavam casar à mão com o DDL de ``persistence/db.py``. Um typo em
qualquer um dos dois só aparecia em runtime.

Aqui os dois viram tipos explícitos, sem dependência de Playwright, LLM ou
banco — a camada mais interna, que as de fora importam mas nunca o contrário.
"""

from src.core.entities.applied_job import AppliedJob, RejectedJob
from src.core.entities.eval_result import EvalResult

__all__ = ["AppliedJob", "RejectedJob", "EvalResult"]
