"""Parsing da resposta do LLM e os rejects determinísticos.

``_parse_eval_line`` é o ponto mais frágil do avaliador: mexe com índices de
uma linha separada por ``|`` cujo formato muda conforme YES ou NO, e um erro
aqui vira vaga rejeitada em silêncio.
"""

import pytest

from src.core.entities.eval_result import EvalResult
from src.core.use_cases.job_evaluator import JobEvaluator, _parse_eval_line


class TestParseEvalLine:
    def test_match_completo(self):
        result = _parse_eval_line("YES|7000|Backend Python remoto|kubernetes,redis|CLT")
        assert result == EvalResult(
            matches=True,
            salary=7000,
            reason="Backend Python remoto",
            missing_skills=["kubernetes", "redis"],
            contract="CLT",
        )

    def test_rejeicao(self):
        result = _parse_eval_line("NO|Requer Angular|angular,typescript")
        assert not result.matches
        assert result.salary is None
        assert result.reason == "Requer Angular"
        assert result.missing_skills == ["angular", "typescript"]
        assert result.contract == "unknown"

    def test_salario_com_formatacao_e_limpo(self):
        assert _parse_eval_line("YES|R$ 11.000,00|ok||PJ").salary == 11000

    # O prompt pede número puro, mas o modelo formata de vez em quando. Tirar só
    # os não-dígitos daria 1100000 — cem vezes o valor, direto no formulário.
    @pytest.mark.parametrize(
        "raw,esperado",
        [
            ("7000", 7000),
            (" 7000 ", 7000),
            ("R$ 7000", 7000),
            ("7.000", 7000),
            ("11.000,00", 11000),
            ("11000.00", 11000),
            ("R$ 14.500,50", 14500),
        ],
    )
    def test_formatos_de_salario(self, raw, esperado):
        assert _parse_eval_line(f"YES|{raw}|ok||CLT").salary == esperado

    def test_salario_ilegivel_nao_quebra(self):
        result = _parse_eval_line("YES|a combinar|ok||CLT")
        assert result.matches
        assert result.salary is None

    def test_skills_vazias(self):
        assert _parse_eval_line("YES|9000|Node fullstack||PJ").missing_skills == []

    def test_skills_normalizadas_para_minusculo(self):
        result = _parse_eval_line("NO|falta stack| Kubernetes , REDIS ")
        assert result.missing_skills == ["kubernetes", "redis"]

    def test_contrato_invalido_vira_unknown(self):
        assert _parse_eval_line("YES|7000|ok||CONSULTOR").contract == "unknown"

    def test_acha_a_linha_util_no_meio_do_ruido(self):
        raw = "Claro! Segue a análise:\nYES|8000|Match de stack||PJ\nEspero ter ajudado"
        result = _parse_eval_line(raw)
        assert result.matches
        assert result.salary == 8000

    def test_resposta_sem_formato_vira_nao_match(self):
        result = _parse_eval_line("não consegui avaliar")
        assert not result.matches
        # A resposta crua vira o motivo, pra não perder o rastro no log.
        assert result.reason == "não consegui avaliar"

    def test_yes_sem_campos_opcionais(self):
        result = _parse_eval_line("YES|5000")
        assert result.matches
        assert result.salary == 5000


class TestEvalResult:
    def test_contract_tag_omite_desconhecido(self):
        assert EvalResult(contract="unknown").contract_tag == ""
        assert EvalResult(contract="").contract_tag == ""
        assert EvalResult(contract="PJ").contract_tag == " (PJ)"

    def test_parse_error_nao_da_match(self):
        result = EvalResult.parse_error()
        assert not result.matches
        assert result.reason == "parse error"

    def test_missing_skills_nao_e_compartilhado_entre_instancias(self):
        a, b = EvalResult(), EvalResult()
        assert a.missing_skills == b.missing_skills == []
        assert a.missing_skills is not b.missing_skills


def _evaluator(preferences: str = "", level: str | list = "") -> JobEvaluator:
    # resume_path inexistente: load_resume_text devolve vazio, e os rejects
    # testados aqui não olham o currículo.
    return JobEvaluator("nao-existe.txt", preferences=preferences, level=level)


class TestQuickReject:
    def test_sem_niveis_configurados_nunca_rejeita(self):
        assert not _evaluator().quick_reject("Senior Developer")

    def test_rejeita_nivel_fora_do_aceito(self):
        assert _evaluator(level=["junior"]).quick_reject("Desenvolvedor Sênior")

    def test_aceita_nivel_pedido(self):
        assert not _evaluator(level=["pleno"]).quick_reject("Dev Pleno")

    def test_titulo_sem_pista_de_nivel_vai_pro_llm(self):
        assert not _evaluator(level=["junior"]).quick_reject("Desenvolvedor Backend")

    def test_aceita_qualquer_um_dos_niveis_da_lista(self):
        ev = _evaluator(level=["junior", "pleno"])
        assert not ev.quick_reject("Dev Junior")
        assert not ev.quick_reject("Dev Pleno")
        assert ev.quick_reject("Tech Lead")


class TestTechReject:
    def test_sem_preferencia_de_stack_nunca_rejeita(self):
        assert not _evaluator().tech_reject("Dev PHP", "Laravel e WordPress")

    def test_rejeita_stack_incompativel(self):
        ev = _evaluator(preferences="Python e Node.js")
        assert ev.tech_reject("Dev PHP", "Vaga para Laravel e WordPress")

    def test_aceita_quando_a_stack_pedida_aparece(self):
        ev = _evaluator(preferences="Python e Node.js")
        assert not ev.tech_reject("Dev Backend", "Django e FastAPI")

    def test_stack_pedida_presente_ganha_de_stack_estranha(self):
        ev = _evaluator(preferences="Python")
        assert not ev.tech_reject("Fullstack", "Django no backend, Angular no front")

    def test_descricao_neutra_vai_pro_llm(self):
        ev = _evaluator(preferences="Python")
        assert not ev.tech_reject("Dev Backend", "Trabalho remoto, time ágil")
