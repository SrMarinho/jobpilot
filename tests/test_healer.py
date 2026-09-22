"""Guard rails da cura in-run.

A cura acontece **com o lock do browser na mão** — e o lock tem teto de 600s
que já foi estourado duas vezes em setembro. Então o que se testa aqui não é
"a cura funciona": é "a cura desiste rápido e pelos motivos certos".

A ordem das desistências também é comportamento: registry, curável, orçamento,
store, quota, checkpoint, e só então LLM. Todas as primeiras são de graça; a
última custa dinheiro. Um teste que aceite a ordem trocada aceitaria pagar LLM
para descobrir que o campo nem era curável.

E a regra que atravessa tudo: nada aqui pode derrubar o run. O run agendado é a
única chance do dia.
"""

import pytest

from src.automation.evolve import healer as healer_mod
from src.automation.evolve.healer import HealBudget, SelectorHealer
from src.core.use_cases.evolve.selector_store import SelectorStore


class FakeProvider:
    def __init__(self, resposta: str = "[data-curado]", explode: bool = False):
        self.resposta = resposta
        self.explode = explode
        self.chamadas = 0

    async def complete(self, prompt: str) -> str:
        self.chamadas += 1
        if self.explode:
            raise RuntimeError("LLM fora do ar")
        return self.resposta


class FakeRepo:
    def __init__(self):
        self.data = {}

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class FakePage:
    def __init__(self):
        self.url = "https://www.linkedin.com/jobs"

    def locator(self, selector):
        raise AssertionError("não deveria chegar a tocar o DOM neste teste")


@pytest.fixture(autouse=True)
def _cura_ligada_e_isolada(monkeypatch):
    """Liga a cura, isola store/quota/telegram/checkpoint do mundo real."""
    monkeypatch.setenv("EVOLVE_HEAL", "true")

    store = SelectorStore(FakeRepo())
    monkeypatch.setattr(healer_mod, "store", lambda: store)
    monkeypatch.setattr("src.core.use_cases.evolve.selector_store.store", lambda: store)
    monkeypatch.setattr(healer_mod, "refresh_overrides", lambda: None)
    monkeypatch.setattr(SelectorHealer, "_record_quota", lambda self: None)
    monkeypatch.setattr(SelectorHealer, "_notify", lambda self, f, v: None)
    monkeypatch.setattr(SelectorHealer, "_quota_ok", lambda self: True)

    async def sem_checkpoint(self):
        return False

    monkeypatch.setattr(SelectorHealer, "_blocked_by_checkpoint", sem_checkpoint)
    return store


def _healer(provider=None, budget=None) -> SelectorHealer:
    return SelectorHealer(
        FakePage(), budget=budget, provider=provider or FakeProvider()
    )


async def _call(healer, field="linkedin job description", kind="visible"):
    return await healer(FakePage(), [".morto"], field=field, kind=kind)


class TestKillSwitch:
    async def test_desligado_por_default(self, monkeypatch):
        """Autonomia não se liga sozinha."""
        monkeypatch.delenv("EVOLVE_HEAL", raising=False)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0

    @pytest.mark.parametrize("valor", ["false", "0", "no", "", "talvez"])
    async def test_valor_nao_afirmativo_mantem_desligado(self, monkeypatch, valor):
        monkeypatch.setenv("EVOLVE_HEAL", valor)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0


class TestDesistenciasSemCusto:
    async def test_campo_fora_do_registry_nao_gasta_llm(self):
        provider = FakeProvider()
        assert await _call(_healer(provider), field="campo inventado") is None
        assert provider.chamadas == 0

    async def test_campo_incuravel_nao_gasta_llm(self):
        """`invite modal`: ausência é o caminho de sucesso, não quebra."""
        provider = FakeProvider()
        assert await _call(_healer(provider), field="invite modal") is None
        assert provider.chamadas == 0

    async def test_campo_ja_tentado_no_run_nao_repete(self):
        provider = FakeProvider()
        budget = HealBudget()
        budget.fields_tried.add("linkedin job description")
        assert await _call(_healer(provider, budget)) is None
        assert provider.chamadas == 0

    async def test_teto_de_curas_por_run(self):
        provider = FakeProvider()
        budget = HealBudget(max_heals=2)
        budget.heals = 2
        assert await _call(_healer(provider, budget)) is None
        assert provider.chamadas == 0

    async def test_teto_de_tempo_por_run(self):
        """O orçamento é do browser lock, não do LLM."""
        provider = FakeProvider()
        budget = HealBudget(max_seconds=60)
        budget.seconds = 61
        assert await _call(_healer(provider, budget)) is None
        assert provider.chamadas == 0

    async def test_campo_marcado_incuravel_no_store_para(self, _cura_ligada_e_isolada):
        store = _cura_ligada_e_isolada
        for _ in range(3):
            store.note_heal_attempt("linkedin job description", ok=False)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0

    async def test_cooldown_impede_insistencia(self, _cura_ligada_e_isolada):
        _cura_ligada_e_isolada.note_heal_attempt("linkedin job description", ok=False)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0

    async def test_quota_estourada_nao_gasta_llm(self, monkeypatch):
        monkeypatch.setattr(SelectorHealer, "_quota_ok", lambda self: False)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0

    async def test_checkpoint_bloqueia(self, monkeypatch):
        """Sob CAPTCHA o DOM não é a página real — aprenderia lixo."""

        async def com_checkpoint(self):
            return True

        monkeypatch.setattr(SelectorHealer, "_blocked_by_checkpoint", com_checkpoint)
        provider = FakeProvider()
        assert await _call(_healer(provider)) is None
        assert provider.chamadas == 0


class TestOrcamento:
    def test_bloqueia_por_campo_repetido(self):
        budget = HealBudget()
        budget.spend("x", 1.0, healed=True)
        assert "já tentado" in budget.blocks("x")
        assert budget.blocks("outro") == ""

    def test_falha_consome_tempo_mas_nao_conta_cura(self):
        budget = HealBudget()
        budget.spend("x", 12.0, healed=False)
        assert budget.heals == 0
        assert budget.seconds == 12.0

    def test_sucesso_conta_cura(self):
        budget = HealBudget()
        budget.spend("x", 3.0, healed=True)
        assert budget.heals == 1

    def test_motivos_sao_legiveis(self):
        cheio = HealBudget(max_heals=1)
        cheio.heals = 1
        assert "teto de 1 curas" in cheio.blocks("y")
        lento = HealBudget(max_seconds=30)
        lento.seconds = 30
        assert "teto de 30s" in lento.blocks("y")


class TestFalhaDoLLM:
    async def test_llm_que_explode_nao_derruba_o_run(self, _cura_ligada_e_isolada):
        healer = _healer(FakeProvider(explode=True))
        assert await _call(healer) is None
        override = _cura_ligada_e_isolada.override("linkedin job description")
        assert override.heal_failures == 1

    async def test_resposta_sem_candidato_conta_como_falha(
        self, _cura_ligada_e_isolada
    ):
        healer = _healer(FakeProvider(resposta="Nao consegui achar nada aqui"))
        assert await _call(healer) is None
        assert (
            _cura_ligada_e_isolada.override("linkedin job description").heal_failures
            == 1
        )

    async def test_tres_falhas_marcam_incuravel(
        self, _cura_ligada_e_isolada, monkeypatch
    ):
        """Para de gastar LLM, mas o campo continua sendo reportado."""
        store = _cura_ligada_e_isolada
        for _ in range(3):
            # Zera o cooldown entre tentativas pra exercitar só o contador.
            store.note_heal_attempt("linkedin job description", ok=False)
        assert store.override("linkedin job description").unhealable


class TestCuraQueDaCerto:
    async def test_aprende_valida_e_devolve_locator(
        self, monkeypatch, _cura_ligada_e_isolada
    ):
        """O run continua de onde parou, no mesmo segundo."""
        from src.automation.evolve import candidate_validator
        from src.automation.evolve.candidate_validator import Validation

        async def aprova_tudo(root, candidates, spec, *, kind="visible"):
            ok = Validation(True, candidates[0], "", 1, "Descrição da vaga")
            return ok, [ok]

        monkeypatch.setattr(candidate_validator, "first_valid", aprova_tudo)
        monkeypatch.setattr(
            candidate_validator, "resolve", lambda root, sel: _FakeLocator(sel)
        )

        async def contexto_falso(root, *, scope="page", max_elements=40):
            return "1. <div> data-test='desc'"

        from src.automation.evolve import dom_context

        monkeypatch.setattr(dom_context, "capture", contexto_falso)

        healer = _healer(FakeProvider(resposta="[data-test='desc']"))
        result = await _call(healer)

        assert result is not None
        store = _cura_ligada_e_isolada
        assert store.candidates("linkedin job description") == ["[data-test='desc']"]
        assert store.override("linkedin job description").heal_failures == 0
        assert healer.healed == [("linkedin job description", "[data-test='desc']")]
        assert healer.budget.heals == 1


class _FakeLocator:
    def __init__(self, selector: str):
        self.selector = selector

    @property
    def first(self):
        return self
