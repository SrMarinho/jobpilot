"""Resolução de selectors com candidatos aprendidos e gancho de cura.

Três garantias que sustentam a autoevolução, e que não podem depender de
browser pra serem verificadas:

1. **O aprendido vence o declarado** — senão a cura não serve pra nada: o run
   seguinte voltaria a tentar o selector morto primeiro.
2. **Sem gancho instalado, nada muda** — a feature tem que ser invisível pra
   quem não ativou. É o que permite ligá-la por partes.
3. **Nem contabilidade nem cura podem derrubar scraping** — o run agendado é a
   única chance do dia; uma exceção aqui custa o dia inteiro.

Os dublês imitam só o que o resolver usa de Playwright: ``locator(sel)`` →
objeto com ``is_visible``/``is_enabled`` e ``.first``.
"""

import pytest

from src.automation.pages import selectors as sel


class FakeLocator:
    def __init__(self, selector: str, visible: bool, enabled: bool = True):
        self.selector = selector
        self._visible = visible
        self._enabled = enabled

    @property
    def first(self):
        return self

    async def is_visible(self, timeout: int = 0) -> bool:
        return self._visible

    async def is_enabled(self) -> bool:
        return self._enabled


class FakePage:
    """Casa apenas os seletores de ``matching``; registra o que foi tentado."""

    def __init__(self, matching: set[str], enabled: bool = True):
        self.matching = matching
        self.enabled = enabled
        self.tried: list[str] = []

    def locator(self, selector: str):
        self.tried.append(selector)
        return FakeLocator(selector, selector in self.matching, self.enabled)


#: ``_learned_for`` real, antes de a fixture autouse trocá-lo por um dublê.
#: Guardado no import porque o teste de resiliência precisa exercitar a função
#: de verdade, e não o dublê que isola os outros testes.
LEARNED_FOR_ORIGINAL = sel._learned_for


@pytest.fixture(autouse=True)
def _sem_gancho_nem_store(monkeypatch):
    """Isola cada teste: sem gancho, sem aprendidos, sem IO no store."""
    sel.clear_heal_hook()
    monkeypatch.setattr(sel, "_learned_for", lambda field: [])
    monkeypatch.setattr(sel, "_note_hit", lambda field, selector: None)
    monkeypatch.setattr(sel, "_note_miss", lambda field: None)
    monkeypatch.delenv("EVOLVE_FAULT_FIELD", raising=False)
    yield
    sel.clear_heal_hook()


class TestComportamentoDeSempre:
    async def test_primeiro_visivel_vence(self):
        page = FakePage({".b"})
        found = await sel.first_visible(page, [".a", ".b", ".c"], field="x")
        assert found.selector == ".b"
        assert page.tried == [".a", ".b"], "para no primeiro que casa"

    async def test_nenhum_casou_devolve_none_e_avisa(self, caplog):
        page = FakePage(set())
        with caplog.at_level("WARNING"):
            assert await sel.first_visible(page, [".a"], field="job title") is None
        assert "campo='job title'" in caplog.text

    async def test_required_false_nao_avisa(self, caplog):
        page = FakePage(set())
        with caplog.at_level("WARNING"):
            assert (
                await sel.first_visible(page, [".a"], field="x", required=False) is None
            )
        assert caplog.text == ""

    async def test_first_enabled_exige_habilitado(self):
        page = FakePage({".a"}, enabled=False)
        assert await sel.first_enabled(page, [".a"], field="btn") is None

    async def test_prefixo_xpath_e_removido(self):
        page = FakePage({"//button"})
        found = await sel.first_visible(page, ["xpath=//button"], field="x")
        assert found.selector == "//button"


class TestAprendidoVenceDeclarado:
    async def test_aprendido_e_tentado_primeiro(self, monkeypatch):
        """O aprendido é o layout de hoje; o declarado é o de quando escreveram."""
        monkeypatch.setattr(sel, "_learned_for", lambda field: ["[data-novo]"])
        page = FakePage({"[data-novo]", ".antigo"})
        found = await sel.first_visible(page, [".antigo"], field="x")
        assert found.selector == "[data-novo]"
        assert page.tried == ["[data-novo]"]

    async def test_declarado_continua_valendo_se_aprendido_morreu(self, monkeypatch):
        monkeypatch.setattr(sel, "_learned_for", lambda field: ["[data-morto]"])
        page = FakePage({".antigo"})
        found = await sel.first_visible(page, [".antigo"], field="x")
        assert found.selector == ".antigo"
        assert page.tried == ["[data-morto]", ".antigo"]

    async def test_aprendido_vai_com_timeout_curto(self, monkeypatch):
        """Aprendido obsoleto custa 1s, não 5s — ele está na frente da fila."""
        monkeypatch.setattr(sel, "_learned_for", lambda field: ["[data-x]"])
        pares = sel._candidates("x", [".declarado"], sel.T_NORMAL)
        assert pares[0] == ("[data-x]", sel.T_FAST, True)
        assert pares[1] == (".declarado", sel.T_NORMAL, False)

    async def test_acerto_do_aprendido_e_contabilizado(self, monkeypatch):
        hits: list[tuple[str, str]] = []
        monkeypatch.setattr(sel, "_learned_for", lambda field: ["[data-x]"])
        monkeypatch.setattr(sel, "_note_hit", lambda f, s: hits.append((f, s)))
        page = FakePage({"[data-x]"})
        await sel.first_visible(page, [".a"], field="job title")
        assert hits == [("job title", "[data-x]")]

    async def test_acerto_do_declarado_nao_conta_como_aprendido(self, monkeypatch):
        hits = []
        monkeypatch.setattr(sel, "_note_hit", lambda f, s: hits.append(s))
        page = FakePage({".a"})
        await sel.first_visible(page, [".a"], field="x")
        assert hits == []

    async def test_erro_geral_e_contabilizado(self, monkeypatch):
        misses = []
        monkeypatch.setattr(sel, "_note_miss", misses.append)
        page = FakePage(set())
        await sel.first_visible(page, [".a"], field="x", required=False)
        assert misses == ["x"]


class TestGanchoDeCura:
    async def test_sem_gancho_o_comportamento_e_o_de_antes(self):
        assert not sel.heal_hook_installed()
        page = FakePage(set())
        assert await sel.first_visible(page, [".a"], field="x") is None

    async def test_gancho_dispara_quando_nada_casa(self):
        chamadas = []

        async def hook(root, selectors, *, field, kind):
            chamadas.append((field, kind, tuple(selectors)))
            return FakeLocator("[data-curado]", True)

        sel.set_heal_hook(hook)
        page = FakePage(set())
        found = await sel.first_visible(page, [".a"], field="job title")
        assert found.selector == "[data-curado]"
        assert chamadas == [("job title", "visible", (".a",))]

    async def test_gancho_recebe_kind_enabled_em_botao(self):
        kinds = []

        async def hook(root, selectors, *, field, kind):
            kinds.append(kind)
            return None

        sel.set_heal_hook(hook)
        await sel.first_enabled(FakePage(set()), [".a"], field="btn")
        assert kinds == ["enabled"]

    async def test_gancho_nao_dispara_quando_algo_casou(self):
        async def hook(root, selectors, *, field, kind):
            raise AssertionError("não deveria ser chamado")

        sel.set_heal_hook(hook)
        page = FakePage({".a"})
        assert (await sel.first_visible(page, [".a"], field="x")).selector == ".a"

    async def test_gancho_nao_dispara_em_campo_opcional(self):
        """Ausência esperada não é quebra — é o caso do modal de convite."""

        async def hook(root, selectors, *, field, kind):
            raise AssertionError("campo opcional não deve gastar cura")

        sel.set_heal_hook(hook)
        page = FakePage(set())
        assert (
            await sel.first_visible(page, [".a"], field="invite modal", required=False)
            is None
        )

    async def test_gancho_que_explode_nao_derruba_o_run(self, caplog):
        """Cura que quebra o run é pior que não curar."""

        async def hook(root, selectors, *, field, kind):
            raise RuntimeError("LLM fora do ar")

        sel.set_heal_hook(hook)
        page = FakePage(set())
        with caplog.at_level("WARNING"):
            assert await sel.first_visible(page, [".a"], field="x") is None
        assert "gancho de cura falhou" in caplog.text

    async def test_gancho_que_devolve_none_cai_no_aviso_de_sempre(self, caplog):
        async def hook(root, selectors, *, field, kind):
            return None

        sel.set_heal_hook(hook)
        with caplog.at_level("WARNING"):
            await sel.first_visible(FakePage(set()), [".a"], field="job title")
        assert "layout pode ter mudado" in caplog.text

    async def test_clear_desinstala(self):
        async def hook(root, selectors, *, field, kind):
            return None

        sel.set_heal_hook(hook)
        assert sel.heal_hook_installed()
        sel.clear_heal_hook()
        assert not sel.heal_hook_installed()


class TestInjecaoDeFalha:
    async def test_campo_alvo_perde_os_declarados(self, monkeypatch):
        """Como se verifica a cura sem esperar o LinkedIn quebrar."""
        monkeypatch.setenv("EVOLVE_FAULT_FIELD", "job title")
        page = FakePage({".a"})
        assert (
            await sel.first_visible(page, [".a"], field="job title", required=False)
            is None
        )
        assert page.tried == [sel._DEAD_SELECTOR]

    async def test_outros_campos_nao_sao_afetados(self, monkeypatch):
        monkeypatch.setenv("EVOLVE_FAULT_FIELD", "job title")
        page = FakePage({".a"})
        found = await sel.first_visible(page, [".a"], field="company name")
        assert found.selector == ".a"

    async def test_sem_env_nada_muda(self):
        assert sel._declared_for("job title", [".a"]) == [".a"]


class TestResilienciaDoStore:
    def test_store_quebrado_nao_cega_o_scraping(self, monkeypatch):
        """Sem aprendidos, o comportamento é o de antes da feature existir."""

        def explode(field):
            raise RuntimeError("doc corrompido")

        monkeypatch.setattr(
            "src.core.use_cases.evolve.selector_store.learned_for", explode
        )
        assert LEARNED_FOR_ORIGINAL("qualquer campo") == []

    def test_flush_sem_store_nao_levanta(self, monkeypatch):
        monkeypatch.setattr(
            "src.core.use_cases.evolve.selector_store.store",
            lambda: (_ for _ in ()).throw(RuntimeError("sem disco")),
        )
        sel.flush_learned()
