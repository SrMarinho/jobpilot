"""Partes puras do caminho de candidatura externa: prompt, parsing e matching.

A extração em si precisa de browser; o que dá pra quebrar em silêncio é o
formato de ida e volta com o LLM e a conversão texto->value das opções.
"""

from src.core.use_cases.apply.external_apply import known_answers_map, needs_answer
from src.core.use_cases.apply.form_extractor import (
    build_answer_prompt,
    describe_field,
    match_option,
    parse_answer_lines,
    ref_selector,
)

CAMPOS = [
    {
        "ref": "f1",
        "tag": "input",
        "type": "text",
        "label": "Qual seu CPF?",
        "required": True,
        "options": [],
        "value": "",
    },
    {
        "ref": "f2",
        "tag": "select",
        "type": None,
        "label": "Aceita contratação PJ?",
        "required": True,
        "options": [["", "Selecione uma opção"], ["1", "Sim"], ["2", "Não"]],
        "value": "",
    },
]


def test_parse_aceita_a_saida_limpa():
    out = parse_answer_lines("f1|08221276367\nf2|Sim", {"f1", "f2"})
    assert out == {"f1": "08221276367", "f2": "Sim"}


def test_parse_ignora_preambulo_e_cerca_de_codigo():
    raw = "Aqui estão as respostas:\n```\nf1|123\n```\nEspero ter ajudado."
    assert parse_answer_lines(raw, {"f1"}) == {"f1": "123"}


def test_parse_descarta_ref_alucinado():
    assert parse_answer_lines("f1|a\nf9|b", {"f1"}) == {"f1": "a"}


def test_parse_aceita_resposta_vazia():
    # "não sei e o campo é opcional" tem que chegar como vazio, não sumir.
    assert parse_answer_lines("f1|", {"f1"}) == {"f1": ""}


def test_parse_nao_quebra_resposta_com_pipe():
    assert parse_answer_lines("f1|Python | Node", {"f1"}) == {"f1": "Python | Node"}


def test_match_option_exato():
    assert match_option("Não", CAMPOS[1]["options"]) == "2"


def test_match_option_ignora_acento_e_caixa():
    assert match_option("nao", CAMPOS[1]["options"]) == "2"


def test_match_option_por_continencia():
    opcoes = [["1", "Sim, aceito PJ"], ["2", "Não aceito"]]
    assert match_option("Sim", opcoes) == "1"


def test_match_option_sem_correspondencia():
    assert match_option("Talvez", [["1", "Sim"], ["2", "Não"]]) is None


def test_describe_field_mostra_rotulo_obrigatoriedade_e_opcoes():
    linha = describe_field(CAMPOS[1])
    assert "f2" in linha
    assert "Aceita contratação PJ?" in linha
    assert "obrigatório" in linha
    assert "Sim" in linha and "Não" in linha


def test_prompt_leva_banco_de_qa_vaga_e_refs():
    prompt = build_answer_prompt(
        CAMPOS,
        job_title="Dev Backend",
        job_description="Python e Node",
        resume="5 anos de backend",
        known_answers={"Informe seu CPF *": "08221276367"},
    )
    assert "Dev Backend" in prompt
    assert "5 anos de backend" in prompt
    # O banco entra inteiro: é ele que resolve "Qual seu CPF?" vs
    # "Informe seu CPF *", que a chave exata do cache não casa.
    assert "Informe seu CPF *" in prompt
    assert "f1" in prompt and "f2" in prompt
    assert "ref|resposta" in prompt


def test_ref_selector_com_e_sem_opcao():
    assert ref_selector("f3") == "[data-jp-ref='f3']"
    assert ref_selector("f3", "sim") == "[data-jp-ref='f3:sim']"


def test_known_answers_map_aceita_os_dois_formatos_do_cache():
    cache = {
        "qual seu cpf?": {"original": "Qual seu CPF?", "answer": "123"},
        "quantos anos voce trabalha com sql?": "6",
        "campo vazio": {"original": "Campo vazio", "answer": ""},
    }
    assert known_answers_map(cache) == {
        "Qual seu CPF?": "123",
        "quantos anos voce trabalha com sql?": "6",
    }


def test_select_em_placeholder_conta_como_nao_respondido():
    # element.value devolve texto, mas o campo está em branco — foi esse engano
    # que fazia o Easy Apply pular obrigatórios e travar na revisão.
    campo = dict(CAMPOS[1], value="Selecione uma opção")
    assert needs_answer(campo) is True


def test_select_respondido_nao_volta_pro_llm():
    assert needs_answer(dict(CAMPOS[1], value="2")) is False


def test_checkbox_opcional_nao_e_pendente():
    campo = {"tag": "input", "type": "checkbox", "required": False, "value": ""}
    assert needs_answer(campo) is False
