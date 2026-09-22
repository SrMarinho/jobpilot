"""Edição mecânica da constante de selector.

Promover um candidato validado não precisa de LLM: a constante é uma
``list[str]`` de módulo e o candidato entra como primeiro item. Cada uso de LLM
com permissão de escrita é um grau de liberdade a mais, então o caminho comum
tem que ser determinístico e testado.

Dois comportamentos que importam mais do que parecem:

- **Preservar comentário e formatação.** As listas de candidatos são cheias de
  comentário explicando por que cada fallback existe; é a documentação que faz
  elas serem legíveis. Foi por isso que o parsing é textual e não via ``ast``.
- **Devolver ``None`` quando não reconhece o formato**, em vez de improvisar.
  Aí o caso irregular vai pro ``claude -p``.
"""

from src.core.use_cases.evolve.constant_editor import (
    insert_candidate,
    promotion_note,
)

FONTE = """from src.automation.pages.selectors import first_visible

# Candidatos por campo, em ordem de preferência (ver selectors.py).
_MODAL_CLOSE = [
    "button[aria-label='Fechar']",
    # PT primeiro: a conta roda em português.
    "button[aria-label='Dismiss']",
]
_OUTRO = ["[data-x]"]


class Page:
    pass
"""


class TestInsercao:
    def test_entra_como_primeiro_item(self):
        """A ordem é de preferência: o aprendido é o layout de hoje."""
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-test-close]")
        assert result
        corpo = result.content.split("_MODAL_CLOSE = [")[1]
        assert corpo.index("[data-test-close]") < corpo.index("aria-label='Fechar'")

    def test_preserva_comentarios_e_demais_candidatos(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-test-close]")
        assert "# PT primeiro: a conta roda em português." in result.content
        assert "button[aria-label='Dismiss']" in result.content
        assert "# Candidatos por campo" in result.content

    def test_nao_mexe_em_outra_constante(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-novo]")
        assert '_OUTRO = ["[data-x]"]' in result.content

    def test_preserva_o_resto_do_arquivo(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-novo]")
        assert result.content.startswith("from src.automation.pages.selectors")
        assert result.content.rstrip().endswith("pass")

    def test_respeita_a_indentacao_existente(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-novo]")
        assert '\n    "[data-novo]",\n' in result.content

    def test_nota_entra_como_comentario(self):
        nota = promotion_note(day="2026-09-21")
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-novo]", note=nota)
        assert f"    # {nota}\n" in result.content
        assert "aprendido em 2026-09-21" in result.content

    def test_resultado_continua_sendo_python_valido(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[data-novo]")
        escopo: dict = {}
        exec(  # noqa: S102 - o objetivo do teste é justamente executar o resultado
            result.content.replace(
                "from src.automation.pages.selectors import first_visible", ""
            ),
            escopo,
        )
        assert escopo["_MODAL_CLOSE"][0] == "[data-novo]"

    def test_aspa_dupla_quando_o_seletor_tem_aspa_simples(self):
        """`repr` cego produziria escape que ninguém escreveria à mão."""
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "[aria-label='Enviar']")
        assert "\"[aria-label='Enviar']\"," in result.content
        assert "\\'" not in result.content


class TestRecusas:
    def test_recusa_selector_vazio(self):
        assert not insert_candidate(FONTE, "_MODAL_CLOSE", "   ")

    def test_recusa_constante_inexistente(self):
        result = insert_candidate(FONTE, "_NAO_EXISTE", "[data-x]")
        assert not result
        assert "não achei o bloco" in result.reason

    def test_recusa_constante_de_uma_linha(self):
        """Formato irregular vai pro caminho do LLM, não pro improviso."""
        result = insert_candidate(FONTE, "_OUTRO", "[data-y]")
        assert not result
        assert "uma linha só" in result.reason

    def test_recusa_duplicata(self):
        result = insert_candidate(FONTE, "_MODAL_CLOSE", "button[aria-label='Fechar']")
        assert not result
        assert "já está na constante" in result.reason


class TestFormatosTolerados:
    def test_constante_anotada(self):
        fonte = '_X: list[str] = [\n    "[data-a]",\n]\n'
        result = insert_candidate(fonte, "_X", "[data-b]")
        assert result
        assert result.content.index("[data-b]") < result.content.index("[data-a]")

    def test_lista_vazia_multi_linha(self):
        fonte = "_X = [\n]\n"
        result = insert_candidate(fonte, "_X", "[data-b]")
        assert result
        assert '"[data-b]"' in result.content or "'[data-b]'" in result.content

    def test_xpath_com_prefixo(self):
        result = insert_candidate(
            FONTE, "_MODAL_CLOSE", "xpath=//button[@aria-label='Fechar']"
        )
        assert result
        assert "xpath=//button" in result.content
