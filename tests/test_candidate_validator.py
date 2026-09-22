"""Validação de candidato na página viva — a barreira que permite a autonomia.

O LLM não decide nada: ele sugere, e o candidato só é aceito se sobreviver a
verificações contra o DOM real. Este teste cobre as reprovações que importam, e
a que mais importa é a do nome acessível.

O cenário que justifica o módulo: o modelo devolve um seletor que casa um
elemento visível, clicável e único — e que é o botão "Denunciar". Contagem e
visibilidade aprovariam. Só ``expect`` reprova. Sem ele, a automação clicaria.

Dublês imitam o mínimo de Playwright usado: ``locator()`` → objeto com
``count``/``first``/``is_visible``/``is_enabled``/``get_attribute``/``evaluate``.
"""

import pytest

from src.automation.evolve.candidate_validator import first_valid, resolve, validate
from src.core.use_cases.evolve.selector_registry import FieldSpec


def spec(**kwargs) -> FieldSpec:
    base = dict(
        field="send invite button",
        module="src.automation.pages.people_search_page",
        constant="_SEND_INVITE",
        intent="botão que envia o convite de conexão sem nota",
    )
    base.update(kwargs)
    return FieldSpec(**base)


class FakeElement:
    def __init__(
        self,
        *,
        visible: bool = True,
        enabled: bool = True,
        aria: str | None = None,
        text: str = "",
        tag: str = "button",
        role: str | None = None,
    ):
        self._visible = visible
        self._enabled = enabled
        self._aria = aria
        self._text = text
        self._tag = tag
        self._role = role

    async def is_visible(self, timeout: int = 0) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled

    async def get_attribute(self, name: str):
        return {"aria-label": self._aria, "role": self._role}.get(name)

    async def inner_text(self) -> str:
        return self._text

    async def evaluate(self, expression: str):
        return self._tag


class FakeMatch:
    def __init__(self, count: int, element: FakeElement):
        self._count = count
        self.first = element

    async def count(self) -> int:
        return self._count


class FakeRoot:
    """Mapa seletor → (quantos casam, elemento)."""

    def __init__(self, table: dict[str, tuple[int, FakeElement]]):
        self.table = table
        self.asked: list[str] = []

    def locator(self, selector: str):
        self.asked.append(selector)
        if selector not in self.table:
            return FakeMatch(0, FakeElement())
        count, element = self.table[selector]
        return FakeMatch(count, element)


class TestRegrasBasicas:
    async def test_aprova_candidato_bom(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="Enviar sem nota"))})
        result = await validate(root, "[data-x]", spec(expect=r"(enviar|send)"))
        assert result
        assert result.matches == 1
        assert result.name == "Enviar sem nota"

    async def test_reprova_antes_de_tocar_a_pagina_se_e_inseguro(self):
        """Regra de segurança roda primeiro: nem chega a consultar o DOM."""
        root = FakeRoot({})
        result = await validate(root, "div, span", spec())
        assert not result
        assert "regra de segurança" in result.reason
        assert root.asked == []

    async def test_reprova_quando_nao_casa_nada(self):
        result = await validate(FakeRoot({}), "[data-x]", spec())
        assert not result
        assert "não casa nenhum elemento" in result.reason

    async def test_reprova_seletor_amplo(self):
        """47 matches passariam a visibilidade e agiriam no elemento errado."""
        root = FakeRoot({"[data-x]": (47, FakeElement(aria="Enviar"))})
        result = await validate(root, "[data-x]", spec(expect=r"enviar"))
        assert not result
        assert "casa 47 elementos" in result.reason

    async def test_max_matches_maior_permite_mais(self):
        root = FakeRoot({"[data-x]": (3, FakeElement(text="Título da vaga"))})
        assert await validate(root, "[data-x]", spec(max_matches=3))

    async def test_reprova_invisivel(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(visible=False))})
        result = await validate(root, "[data-x]", spec())
        assert not result
        assert "não está visível" in result.reason

    async def test_xpath_e_desprefixado(self):
        root = FakeRoot({"//button": (1, FakeElement(text="ok"))})
        assert await validate(root, "xpath=//button", spec())

    def test_resolve_nao_usa_first(self):
        """A contagem tem que ver todos os nós — é assim que pega amplo demais."""
        root = FakeRoot({"[data-x]": (5, FakeElement())})
        assert isinstance(resolve(root, "[data-x]"), FakeMatch)


class TestCampoClicavel:
    async def test_reprova_desabilitado(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="Enviar", enabled=False))})
        result = await validate(
            root, "[data-x]", spec(expect=r"enviar", clicked=True), kind="enabled"
        )
        assert not result
        assert "desabilitado" in result.reason

    async def test_reprova_tag_nao_clicavel(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="Enviar", tag="div"))})
        result = await validate(
            root, "[data-x]", spec(expect=r"enviar", clicked=True), kind="enabled"
        )
        assert not result
        assert "não é elemento clicável" in result.reason

    async def test_aceita_div_com_role_button(self):
        root = FakeRoot(
            {"[data-x]": (1, FakeElement(aria="Enviar", tag="div", role="button"))}
        )
        assert await validate(
            root, "[data-x]", spec(expect=r"enviar", clicked=True), kind="enabled"
        )

    async def test_spec_clicado_exige_estado_mesmo_em_kind_visible(self):
        """`glassdoor apply button` resolve por first_visible mas é clicado."""
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="Apply", enabled=False))})
        result = await validate(
            root, "[data-x]", spec(expect=r"apply", clicked=True), kind="visible"
        )
        assert not result
        assert "desabilitado" in result.reason


class TestNomeAcessivel:
    async def test_reprova_botao_errado(self):
        """O cenário que justifica o módulo: visível, único, clicável — e errado.

        Sem `expect`, a automação clicaria em "Denunciar" achando que era
        "Enviar convite".
        """
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="Denunciar publicação"))})
        result = await validate(
            root,
            "[data-x]",
            spec(expect=r"(enviar|send)", clicked=True),
            kind="enabled",
        )
        assert not result
        assert "não casa o esperado" in result.reason
        assert "Denunciar" in result.reason

    async def test_casa_ignorando_caixa(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(aria="ENVIAR SEM NOTA"))})
        assert await validate(root, "[data-x]", spec(expect=r"enviar"))

    async def test_usa_texto_quando_nao_tem_aria(self):
        root = FakeRoot({"[data-x]": (1, FakeElement(text="  Enviar   agora  "))})
        result = await validate(root, "[data-x]", spec(expect=r"enviar"))
        assert result
        assert result.name == "Enviar agora"

    async def test_sem_expect_qualquer_nome_passa(self):
        """Campo de leitura não corre risco de clique — não precisa de expect."""
        root = FakeRoot({"[data-x]": (1, FakeElement(text="qualquer coisa"))})
        assert await validate(root, "[data-x]", spec(field="linkedin job description"))


class TestFirstValid:
    async def test_devolve_o_primeiro_aprovado(self):
        root = FakeRoot(
            {
                "[data-ruim]": (99, FakeElement(aria="Enviar")),
                "[data-bom]": (1, FakeElement(aria="Enviar sem nota")),
            }
        )
        aprovado, laudos = await first_valid(
            root, ["[data-ruim]", "[data-bom]"], spec(expect=r"enviar")
        )
        assert aprovado.selector == "[data-bom]"
        assert len(laudos) == 2

    async def test_devolve_laudo_de_todos_quando_nenhum_passa(self):
        """As reprovações são o material de diagnóstico."""
        root = FakeRoot({"[data-a]": (0, FakeElement())})
        aprovado, laudos = await first_valid(root, ["[data-a]", "div"], spec())
        assert aprovado is None
        assert [v.ok for v in laudos] == [False, False]
        assert "não casa nenhum elemento" in laudos[0].reason
        assert "genérico" in laudos[1].reason

    async def test_lista_vazia_nao_quebra(self):
        aprovado, laudos = await first_valid(FakeRoot({}), [], spec())
        assert aprovado is None
        assert laudos == []


class TestNuncaLevanta:
    async def test_locator_que_explode_vira_reprovacao(self):
        class RootQueExplode:
            def locator(self, selector):
                raise RuntimeError("seletor inválido no engine")

        result = await validate(RootQueExplode(), "[data-x]", spec())
        assert not result
        assert "seletor inválido" in result.reason

    @pytest.mark.parametrize("metodo", ["is_visible", "is_enabled"])
    async def test_checagem_que_explode_vira_reprovacao(self, metodo):
        element = FakeElement(aria="Enviar")

        async def explode(*args, **kwargs):
            raise RuntimeError("detached")

        setattr(element, metodo, explode)
        root = FakeRoot({"[data-x]": (1, element)})
        result = await validate(
            root, "[data-x]", spec(expect=r"enviar", clicked=True), kind="enabled"
        )
        assert not result
        assert "falha ao checar" in result.reason
