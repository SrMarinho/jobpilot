"""Um <select> no placeholder ainda está vazio, mas `element.value` devolve o
texto do rótulo — tratar isso como preenchido pulava campos obrigatórios e
travava o Easy Apply na etapa de revisão."""

import pytest

from src.core.use_cases.apply.field_filler import is_placeholder


@pytest.mark.parametrize(
    "value",
    [
        "",
        None,
        # Wording real do LinkedIn PT-BR 2026, com acento.
        "Selecionar opção",
        "selecionar opcao",
        "Selecione...",
        "Selecione uma opção",
        "Select...",
        "Select an option",
        "  Escolher  ",
        "Nenhum",
    ],
)
def test_placeholder_conta_como_vazio(value):
    assert is_placeholder(value)


@pytest.mark.parametrize(
    "value",
    [
        "Sim",
        "Brasil (+55)",
        "temarinho76@gmail.com",
        "3 anos",
        # Não confundir uma opção real que contém a palavra.
        "Selecionar mais tarde na entrevista",
    ],
)
def test_valor_real_nao_e_placeholder(value):
    assert not is_placeholder(value)


class TestNumericValue:
    """O LLM responde em linguagem natural; campo numérico do LinkedIn rejeita
    a resposta inteira se vier com unidade junto."""

    @pytest.mark.parametrize(
        "resposta,esperado",
        [
            ("3 anos", "3"),
            ("R$ 8.000", "8000"),
            ("8.000,50", "8000.50"),
            ("3,5", "3.5"),
            ("5", "5"),
            ("cerca de 4 anos de experiência", "4"),
            ("1.234.567", "1234567"),
        ],
    )
    def test_extrai_o_numero(self, resposta, esperado):
        from src.core.use_cases.apply.field_filler import numeric_value

        assert numeric_value(resposta) == esperado

    @pytest.mark.parametrize("resposta", ["", "não sei", "Sim"])
    def test_sem_numero_devolve_vazio(self, resposta):
        from src.core.use_cases.apply.field_filler import numeric_value

        assert numeric_value(resposta) == ""


class TestLooksNumericQuestion:
    """O input desses campos é type="text" puro — o enunciado é o único sinal
    de que o LinkedIn só vai aceitar número."""

    @pytest.mark.parametrize(
        "pergunta",
        [
            "Quanto anos utiliza HTML, CSS e JavaScript?",
            "Quantos anos de experiência com Python?",
            "How many years of experience do you have?",
            "Qual sua pretensão de remuneração fixa mensal?",
            "Expected compensation",
        ],
    )
    def test_pergunta_numerica(self, pergunta):
        from src.core.use_cases.apply.field_filler import looks_numeric_question

        assert looks_numeric_question(pergunta)

    @pytest.mark.parametrize(
        "pergunta",
        [
            "Possui experiência realizando QA/testes?",
            "Número de celular",
            "Qual seu nível de inglês?",
            "",
        ],
    )
    def test_pergunta_nao_numerica(self, pergunta):
        from src.core.use_cases.apply.field_filler import looks_numeric_question

        assert not looks_numeric_question(pergunta)
