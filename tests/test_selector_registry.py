"""Contrato entre o registry e as constantes de selector das pages.

Este é o teste que um patch automático ruim arrebenta primeiro, e é de longe o
mais barato do conjunto: ele importa cada page de verdade e confere que a
constante citada existe, tem a forma esperada e passa as regras de segurança.

Dois tipos de erro que ele pega:

- **Drift**: alguém renomeia ``_INVITE_MODAL`` e o registry aponta pro vazio.
  Sem este teste, isso só apareceria quando uma cura tentasse promover o
  candidato — em produção, de madrugada.
- **Selector perigoso**: candidato com vírgula de topo (casa dois seletores e
  estoura o strict mode do Playwright) entrando no código, seja por mão humana
  ou por patch de LLM.

A regra de segurança que mais importa está em ``test_campo_clicavel_tem_expect``:
campo que vai ser **clicado** precisa declarar o que o nome acessível do
elemento deve casar. Sem isso, um candidato alucinado pode ser o botão
"Denunciar" — e a automação clica.
"""

import re

import pytest

from src.core.use_cases.evolve.selector_registry import (
    FIELD_SPECS,
    UNREACHABLE,
    healable_fields,
    spec_for,
)
from src.core.use_cases.evolve.selector_store import is_safe_candidate

TODOS = sorted(FIELD_SPECS)


class TestContratoDasConstantes:
    @pytest.mark.parametrize("field", TODOS)
    def test_constante_existe_e_e_lista_de_strings(self, field):
        candidatos = FIELD_SPECS[field].resolve_constant()
        assert isinstance(candidatos, list), f"{field}: constante não é lista"
        assert candidatos, f"{field}: lista vazia"
        assert all(isinstance(c, str) for c in candidatos), f"{field}: item não-str"

    @pytest.mark.parametrize("field", TODOS)
    def test_sem_candidato_duplicado(self, field):
        candidatos = FIELD_SPECS[field].resolve_constant()
        assert len(candidatos) == len(set(candidatos)), f"{field}: candidato repetido"

    @pytest.mark.parametrize("field", TODOS)
    def test_todo_candidato_declarado_passa_as_regras(self, field):
        """O código de hoje é o piso: nenhuma cura pode piorar isso."""
        for candidato in FIELD_SPECS[field].resolve_constant():
            ok, motivo = is_safe_candidate(candidato)
            assert ok, f"{field}: {candidato!r} rejeitado — {motivo}"

    @pytest.mark.parametrize("field", TODOS)
    def test_xpath_compila(self, field):
        for candidato in FIELD_SPECS[field].resolve_constant():
            if candidato.startswith("xpath="):
                corpo = candidato[len("xpath=") :]
                assert corpo.startswith(("/", "(", ".")), f"{field}: xpath torto"


class TestFormaDoRegistry:
    def test_chave_bate_com_o_campo(self):
        for chave, spec in FIELD_SPECS.items():
            assert chave == spec.field

    def test_nomes_de_campo_sao_unicos_entre_pages(self):
        """A chave é só o nome do campo porque é tudo que o log carrega.

        ``extract_field`` devolve "invite modal", sem a página. Se dois módulos
        usassem o mesmo nome, a cura não teria como saber qual constante
        promover — então a unicidade deixa de ser convenção e passa a ser
        contrato verificado.
        """
        assert len(FIELD_SPECS) == len({s.field for s in FIELD_SPECS.values()})

    def test_cada_campo_aponta_para_uma_constante_distinta(self):
        alvos = [(s.module, s.constant) for s in FIELD_SPECS.values()]
        assert len(alvos) == len(set(alvos)), "dois campos na mesma constante"

    @pytest.mark.parametrize("field", TODOS)
    def test_intencao_e_descritiva(self, field):
        """A intenção vai no prompt de cura; uma linha vaga gera chute."""
        assert len(FIELD_SPECS[field].intent) >= 30

    @pytest.mark.parametrize("field", TODOS)
    def test_escopo_conhecido(self, field):
        assert FIELD_SPECS[field].scope in {"page", "dialog", "card"}

    @pytest.mark.parametrize("field", TODOS)
    def test_max_matches_positivo(self, field):
        assert FIELD_SPECS[field].max_matches >= 1

    @pytest.mark.parametrize("field", TODOS)
    def test_expect_e_regex_valida(self, field):
        expect = FIELD_SPECS[field].expect
        if expect is not None:
            re.compile(expect)


class TestRegrasDeSeguranca:
    @pytest.mark.parametrize("field", TODOS)
    def test_campo_clicavel_tem_expect(self, field):
        """A trava que impede a automação de clicar no botão errado.

        Um candidato proposto por LLM para um campo clicável vai ser clicado de
        verdade — e no LinkedIn isso manda convite, DM ou denúncia em nome do
        usuário. Campo clicável sem ``expect`` é declarado incurável; este teste
        garante que a alternativa (clicar no escuro) não existe.
        """
        spec = FIELD_SPECS[field]
        if spec.clicked:
            assert spec.expect, f"{field}: clicável sem expect — declare ou marque"
            assert spec.healable, f"{field}: clicável com expect deveria ser curável"

    def test_invite_modal_nao_e_curavel(self):
        """O caso dos 711 warnings: ausência do modal é o caminho de sucesso.

        ``invitation_handler`` confirma o envio por ``pending_count()`` logo
        depois de o modal não aparecer. Curar aqui seria caçar pra sempre um
        modal que o LinkedIn não abre mais.
        """
        spec = spec_for("invite modal")
        assert spec.expected_absent
        assert not spec.healable
        assert "711" in spec.absent_note or "pending_count" in spec.absent_note

    def test_existem_campos_curaveis(self):
        curaveis = healable_fields()
        assert len(curaveis) >= 8
        assert "invite modal" not in curaveis
        assert "linkedin job description" in curaveis

    def test_campos_fora_de_alcance_estao_documentados(self):
        """Lacuna conhecida vale mais escrita que esquecida."""
        assert "connect button" in UNREACHABLE
        for nome, motivo in UNREACHABLE.items():
            assert len(motivo) > 40, f"{nome}: motivo raso"
            assert nome not in FIELD_SPECS, f"{nome}: inalcançável e no registry"


class TestCoberturaDoCodigo:
    def test_todo_campo_usado_nas_pages_esta_no_registry(self):
        """Campo novo numa page sem entrada aqui = cura cega naquele campo.

        Varre os ``field="..."`` das pages e cobra registro. Se um campo novo
        aparecer, este teste falha em code review — não em produção.
        """
        from pathlib import Path

        pages = Path("src/automation/pages")
        usados: set[str] = set()
        for arquivo in pages.glob("*.py"):
            texto = arquivo.read_text(encoding="utf-8")
            usados.update(re.findall(r'field="([^"]+)"', texto))

        faltando = usados - set(FIELD_SPECS) - set(UNREACHABLE)
        assert not faltando, (
            f"campos usados nas pages sem entrada no registry: {sorted(faltando)}"
        )
