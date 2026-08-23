"""Uma recusa do LLM gravada como resposta trava o Easy Apply: o LinkedIn
rejeita o valor, o modal não avança e o run gasta os 30 passos sem enviar."""

import pytest

from src.core.use_cases.apply.form_answerer import looks_like_refusal


@pytest.mark.parametrize(
    "answer",
    [
        # O caso real, colhido do cache de produção.
        "No phone number in profile data. Need actual number to fill this — can't fabricate.",
        "I don't have access to that information.",
        "As an AI, I cannot provide a real phone number.",
        "Não tenho essa informação no currículo.",
        "Não posso preencher esse campo.",
        # Explicação longa no lugar de um valor.
        "Well, " + "considerando o contexto da vaga " * 20,
    ],
)
def test_recusa_nao_e_resposta(answer):
    assert looks_like_refusal(answer)


@pytest.mark.parametrize(
    "answer",
    ["11987654321", "5", "Sim", "Yes", "R$ 7.000", "Python, Django, PostgreSQL", ""],
)
def test_valor_preenchivel_passa(answer):
    assert not looks_like_refusal(answer)


class TestPersonalAnswer:
    """Telefone vem da config, não do LLM — foi o campo que travou o Easy Apply."""

    def test_pergunta_de_celular_usa_a_config(self, monkeypatch):
        from src.core.use_cases.apply.form_answerer import personal_answer

        monkeypatch.setenv("USER_PHONE", "11987654321")
        for q in ["Número de celular", "Mobile phone number", "Telefone"]:
            assert personal_answer(q) == "11987654321"

    def test_codigo_do_pais_nao_recebe_o_numero(self, monkeypatch):
        from src.core.use_cases.apply.form_answerer import personal_answer

        monkeypatch.setenv("USER_PHONE", "11987654321")
        assert personal_answer("Código do país do telefone") is None
        assert personal_answer("Phone country code") is None

    def test_sem_config_nao_inventa(self, monkeypatch):
        from src.core.use_cases.apply.form_answerer import personal_answer

        monkeypatch.setenv("USER_PHONE", "")
        assert personal_answer("Número de celular") is None

    def test_pergunta_nao_pessoal_segue_o_fluxo_normal(self, monkeypatch):
        from src.core.use_cases.apply.form_answerer import personal_answer

        monkeypatch.setenv("USER_PHONE", "11987654321")
        assert personal_answer("Anos de experiência com Python") is None
