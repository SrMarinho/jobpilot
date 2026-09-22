"""Prompt de cura e parsing da resposta do LLM.

O prompt é o que separa uma cura útil de um chute: se a intenção do campo e as
proibições não estiverem escritas, o modelo devolve CSS idiomático — e CSS
idiomático inclui ``a, b``, que casa os dois seletores ao mesmo tempo e estoura
o strict mode do Playwright. O projeto já pagou esse bug uma vez.

O parser é tolerante de propósito: modelo local devolve ``<think>``, modelo
grande embrulha em markdown ou numera a lista. Ele não é barreira de segurança
— quem barra é ``is_safe_candidate`` e a validação na página viva.
"""

import pytest

from src.core.use_cases.evolve.heal_prompt import (
    MAX_CANDIDATES,
    build_heal_prompt,
    parse_candidates,
)

DOM = """Página: Vagas (/jobs/search)
1. <button>  aria-label='Enviar sem nota'  60x30"""


def _prompt(**kwargs):
    base = dict(
        field="send invite button",
        intent="botão que envia o convite sem nota",
        scope="dialog",
        kind="enabled",
        failed=["button[aria-label='Enviar sem nota']"],
        dom_context=DOM,
    )
    base.update(kwargs)
    return build_heal_prompt(**base)


class TestBuildHealPrompt:
    def test_carrega_o_essencial(self):
        texto = _prompt()
        assert "send invite button" in texto
        assert "botão que envia o convite sem nota" in texto
        assert "button[aria-label='Enviar sem nota']" in texto
        assert DOM in texto

    def test_proibe_virgula_de_topo(self):
        """A proibição precisa estar escrita: `a, b` é CSS idiomático."""
        texto = _prompt()
        assert "PROIBIDO vírgula" in texto
        assert "strict mode" in texto

    def test_proibe_generico_e_atributo_inventado(self):
        texto = _prompt()
        assert '"div"' in texto or "'div'" in texto or " div" in texto
        assert "Não" in texto and "invente" in texto

    def test_expect_entra_quando_declarado(self):
        texto = _prompt(expect=r"(enviar|send)")
        assert "(enviar|send)" in texto
        assert "nome acessível" in texto

    def test_sem_expect_nao_promete_nada(self):
        assert "nome acessível" not in _prompt(expect=None)

    def test_max_matches_aparece(self):
        assert "no máximo 3 elemento" in _prompt(max_matches=3)

    def test_escopo_e_traduzido(self):
        assert "modal/diálogo" in _prompt(scope="dialog")
        assert "card da lista" in _prompt(scope="card")
        assert "página inteira" in _prompt(scope="page")

    def test_kind_muda_a_descricao_do_alvo(self):
        assert "clicável" in _prompt(kind="enabled")
        assert "clicável" not in _prompt(kind="visible")

    def test_sem_candidato_declarado_nao_mente(self):
        assert "(nenhum declarado)" in _prompt(failed=[])


class TestParseCandidates:
    def test_uma_linha_por_seletor(self):
        assert parse_candidates("[data-a]\n[data-b]") == ["[data-a]", "[data-b]"]

    def test_remove_think_de_modelo_local(self):
        raw = "<think>vou olhar o aria-label...</think>\n[data-test='x']"
        assert parse_candidates(raw) == ["[data-test='x']"]

    def test_remove_fence_de_markdown(self):
        raw = "```css\n[data-test='x']\n```"
        assert parse_candidates(raw) == ["[data-test='x']"]

    def test_remove_numeracao_e_bullet(self):
        raw = "1. [data-a]\n- [data-b]\n* [data-c]"
        assert parse_candidates(raw) == ["[data-a]", "[data-b]", "[data-c]"]

    def test_remove_backtick_inline(self):
        assert parse_candidates("`[data-a]`") == ["[data-a]"]

    def test_descarta_prosa(self):
        raw = "Aqui estao os seletores que encontrei\n[data-a]"
        assert parse_candidates(raw) == ["[data-a]"]

    def test_descarta_tag_nua(self):
        """`button` sozinho é genérico e seria reprovado depois de qualquer forma."""
        assert parse_candidates("button\n[data-a]") == ["[data-a]"]

    def test_mantem_seletor_com_espaco(self):
        """Seletor descendente é legítimo — contar palavras não serve de filtro."""
        assert parse_candidates("div[role='dialog'] button.primary") == [
            "div[role='dialog'] button.primary"
        ]

    def test_mantem_xpath(self):
        raw = "xpath=//button[contains(@aria-label,'Enviar')]"
        assert parse_candidates(raw) == [raw]

    def test_nao_repete(self):
        assert parse_candidates("[data-a]\n[data-a]") == ["[data-a]"]

    def test_respeita_o_limite(self):
        raw = "\n".join(f"[data-{i}]" for i in range(10))
        assert len(parse_candidates(raw)) == MAX_CANDIDATES

    @pytest.mark.parametrize("raw", ["", "   ", "\n\n", "# comentário"])
    def test_resposta_inutil_devolve_vazio(self, raw):
        assert parse_candidates(raw) == []
