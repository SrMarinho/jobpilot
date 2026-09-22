"""Classificação de incidente crônico e a ação que cada categoria dispara.

Contar ocorrências diz *que* algo se repete; não diz *o que fazer*. Um mesmo
WARNING repetido pode pedir três ações opostas — curar, consertar a expectativa
ou aposentar — e escolher errado custa LLM pra sempre. Foi o que os 711 avisos
de ``invite modal`` mostraram: eram o caminho de sucesso sendo logado como
falha.

O que se testa aqui, principalmente, é a **contenção**: confiança baixa não
age, ``platform_changed`` não gera patch (redesenho não é validável por
pytest), e campo declarado incurável não vira job por via nenhuma.
"""

from datetime import date

import pytest

from src.core.use_cases.evolve.diagnosis import (
    CAT_BUG,
    CAT_NOISE,
    CAT_PLATFORM_CHANGED,
    CAT_PLATFORM_GONE,
    CAT_SELECTOR,
    Diagnosis,
    build_diagnosis_prompt,
    parse_diagnoses,
    plan_action,
)
from src.core.use_cases.evolve.log_scan import Incident
from src.core.use_cases.evolve.queue import (
    KIND_DEMOTE_LOG,
    KIND_PATCH_BUG,
    KIND_RETIRE_FEATURE,
)


def _incident(**kwargs) -> Incident:
    base = dict(
        sig="ab12cd34ef",
        level="WARNING",
        task="connect",
        template="campo=invite modal: nenhum candidato casou",
    )
    base.update(kwargs)
    incident = Incident(**base)
    incident.count = kwargs.pop("count", 711)
    incident.days = {date(2026, 9, d + 1) for d in range(15)}
    incident.fields = kwargs.get("fields", {"invite modal"})
    incident.samples = ["amostra do log"]
    return incident


def _diag(cat: str, conf: float = 0.9) -> Diagnosis:
    return Diagnosis(sig="ab12cd34ef", category=cat, confidence=conf, reason="porque")


class TestPrompt:
    def test_carrega_a_evidencia_que_permite_decidir(self):
        texto = build_diagnosis_prompt([_incident()])
        assert "ab12cd34ef" in texto
        assert "connect" in texto
        assert "invite modal" in texto
        assert "711" in texto

    def test_descreve_todas_as_categorias(self):
        texto = build_diagnosis_prompt([_incident()])
        for categoria in (
            CAT_SELECTOR,
            CAT_PLATFORM_GONE,
            CAT_PLATFORM_CHANGED,
            CAT_BUG,
            CAT_NOISE,
        ):
            assert categoria in texto

    def test_pede_confianca_baixa_quando_nao_da_pra_decidir(self):
        assert "abaixo de 0.7" in build_diagnosis_prompt([_incident()])

    def test_lote_com_varios_itens(self):
        texto = build_diagnosis_prompt(
            [_incident(), _incident(sig="ffffffffff", task="engage")]
        )
        assert "ab12cd34ef" in texto and "ffffffffff" in texto


class TestParse:
    def test_linha_bem_formada(self):
        result = parse_diagnoses("ab12cd34ef|selector|0.9|o seletor nao casa mais")
        assert len(result) == 1
        assert result[0].category == CAT_SELECTOR
        assert result[0].confidence == 0.9
        assert result[0].reason == "o seletor nao casa mais"

    def test_remove_think_de_modelo_local(self):
        raw = "<think>hmm</think>\nab12cd34ef|noise|0.8|ruido de rede"
        assert parse_diagnoses(raw)[0].category == CAT_NOISE

    def test_ignora_linha_malformada_em_vez_de_adivinhar(self):
        raw = (
            "Aqui esta a classificacao:\n"
            "ab12cd34ef|selector|0.9|ok\n"
            "linha sem pipes\n"
            "xx|selector|0.9|id curto demais\n"
        )
        assert [d.sig for d in parse_diagnoses(raw)] == ["ab12cd34ef"]

    def test_ignora_categoria_inventada(self):
        assert parse_diagnoses("ab12cd34ef|categoria_nova|0.9|x") == []

    def test_ignora_confianca_nao_numerica(self):
        assert parse_diagnoses("ab12cd34ef|selector|alta|x") == []

    def test_nao_repete_o_mesmo_id(self):
        raw = "ab12cd34ef|selector|0.9|a\nab12cd34ef|bug|0.9|b"
        result = parse_diagnoses(raw)
        assert len(result) == 1
        assert result[0].category == CAT_SELECTOR

    def test_confianca_e_limitada_ao_intervalo(self):
        assert parse_diagnoses("ab12cd34ef|bug|3.5|x")[0].confidence == 1.0

    @pytest.mark.parametrize("raw", ["", "   ", "nada aqui"])
    def test_resposta_inutil_devolve_vazio(self, raw):
        assert parse_diagnoses(raw) == []


class TestContencao:
    def test_confianca_baixa_nao_age(self):
        """Classificação incerta que dispara patch gasta LLM e produz lixo."""
        job, motivo = plan_action(_incident(), _diag(CAT_BUG, conf=0.5))
        assert job is None
        assert "confiança baixa" in motivo

    def test_platform_changed_nunca_gera_patch(self):
        """Redesenho de fluxo não é validável por pytest."""
        job, motivo = plan_action(_incident(), _diag(CAT_PLATFORM_CHANGED))
        assert job is None
        assert "decisão humana" in motivo

    def test_ruido_e_silenciado_nao_corrigido(self):
        job, motivo = plan_action(_incident(), _diag(CAT_NOISE))
        assert job is None
        assert "silenciado" in motivo

    def test_campo_incuravel_nao_vira_job(self):
        """`invite modal` é expected_absent: ausência é o caminho de sucesso."""
        job, motivo = plan_action(_incident(), _diag(CAT_SELECTOR))
        assert job is None
        assert "incurável" in motivo

    def test_campo_fora_do_registry_nao_vira_job(self):
        job, motivo = plan_action(
            _incident(fields={"campo inventado"}), _diag(CAT_SELECTOR)
        )
        assert job is None
        assert "não está no registry" in motivo

    def test_selector_sem_campo_citado_nao_vira_job(self):
        job, motivo = plan_action(_incident(fields=set()), _diag(CAT_SELECTOR))
        assert job is None
        assert "sem campo" in motivo

    def test_selector_curavel_espera_o_dom(self):
        """O drain não tem browser — a cura precisa do DOM vivo."""
        job, motivo = plan_action(
            _incident(fields={"linkedin job description"}), _diag(CAT_SELECTOR)
        )
        assert job is None
        assert "próximo run" in motivo

    def test_motivo_e_sempre_preenchido(self):
        """ "Não fiz nada e não digo por quê" é o que este sistema não pode ser."""
        for categoria in (
            CAT_SELECTOR,
            CAT_PLATFORM_GONE,
            CAT_PLATFORM_CHANGED,
            CAT_BUG,
            CAT_NOISE,
        ):
            _, motivo = plan_action(_incident(), _diag(categoria))
            assert motivo.strip()


class TestAcoes:
    def test_feature_morta_vira_aposentadoria(self):
        """O caso SSI: nenhum override de banco conserta isso."""
        incident = _incident(
            task="profile-capture",
            template="SSI scrape falhou (acesso descontinuado)",
            fields=set(),
        )
        job, motivo = plan_action(incident, _diag(CAT_PLATFORM_GONE))
        assert job == KIND_RETIRE_FEATURE
        assert "descontinuada" in motivo

    def test_aviso_com_campo_vira_rebaixamento_de_log(self):
        job, _ = plan_action(_incident(level="WARNING"), _diag(CAT_BUG))
        assert job == KIND_DEMOTE_LOG

    def test_erro_de_verdade_vira_patch(self):
        incident = _incident(
            level="ERROR", template="TypeError: NoneType não é iterável", fields=set()
        )
        job, _ = plan_action(incident, _diag(CAT_BUG))
        assert job == KIND_PATCH_BUG
