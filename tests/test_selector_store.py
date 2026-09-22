"""Regras de segurança e contabilidade dos selectors aprendidos.

``is_safe_candidate`` é a primeira barreira contra um LLM criativo, e roda
antes de qualquer validação na página. O caso que mais importa é a vírgula de
topo: ``locator("a, b")`` casa os dois seletores ao mesmo tempo e estoura o
strict mode do Playwright — bug que o projeto já pagou e documentou em
``selectors.py``. Deixar a cura reintroduzir isso seria repetir de graça.

A contabilidade existe porque selector aprendido não é verdade eterna: o layout
muda de novo. Sem descarte automático, o store acumula seletores mortos que
custam 1s cada na frente da fila de candidatos.
"""

from datetime import datetime, timedelta

import pytest

from src.core.use_cases.evolve.selector_store import (
    MAX_HEAL_FAILURES,
    MAX_MISSES,
    FieldOverride,
    SelectorStore,
    is_safe_candidate,
)


class FakeRepo:
    """DocRepo em memória — o store não deve tocar disco nem banco no teste."""

    def __init__(self, data: dict | None = None):
        self.data = data or {}
        self.saves = 0

    def load(self) -> dict:
        return self.data

    def save(self, data: dict) -> None:
        self.data = data
        self.saves += 1


@pytest.fixture
def store():
    return SelectorStore(FakeRepo())


class TestIsSafeCandidate:
    @pytest.mark.parametrize(
        "selector",
        [
            "[data-test-modal-container]",
            "button[aria-label='Enviar sem nota']",
            "xpath=//button[contains(@aria-label,'Enviar')]",
            "xpath=(//div[@role='dialog'])[1]",
            "div[role='dialog'] button.primary",
            ".artdeco-modal",
            "[aria-label='a, b']",  # vírgula dentro de aspas é legítima
            "button:is(.a,.b)",  # vírgula dentro de :is() é legítima
        ],
    )
    def test_aceita_seletor_legitimo(self, selector):
        ok, motivo = is_safe_candidate(selector)
        assert ok, motivo

    def test_rejeita_virgula_de_topo(self):
        """O bug que o projeto já pagou: casa os dois e estoura strict mode."""
        ok, motivo = is_safe_candidate("[role='dialog'], .artdeco-modal")
        assert not ok
        assert "strict mode" in motivo

    @pytest.mark.parametrize(
        "selector,trecho",
        [
            ("", "vazio"),
            ("   ", "vazio"),
            ("*", "genérico"),
            ("div", "genérico"),
            ("BODY", "genérico"),
            ("div > span", "genérico"),
            ("x" * 900, "longo"),
            ("button\n.foo", "quebra de linha"),
            ("xpath=", "vazio"),
            ("xpath=button", "não começa"),
        ],
    )
    def test_rejeita_seletor_perigoso_ou_torto(self, selector, trecho):
        ok, motivo = is_safe_candidate(selector)
        assert not ok
        assert trecho in motivo

    def test_xpath_longo_legitimo_passa(self):
        """O `_EASY_APPLY` real tem 573 chars por causa do translate()."""
        longo = "xpath=//*[" + "contains(@aria-label,'x') and " * 15 + "true()]"
        assert 300 < len(longo) < 800
        ok, _ = is_safe_candidate(longo)
        assert ok


class TestLearn:
    def test_aprende_e_devolve_como_candidato(self, store):
        assert store.learn("job title", "[data-test='title']")
        assert store.candidates("job title") == ["[data-test='title']"]

    def test_recusa_candidato_inseguro(self, store):
        assert not store.learn("job title", "div, span")
        assert store.candidates("job title") == []

    def test_nao_duplica(self, store):
        assert store.learn("job title", "[data-x]")
        assert not store.learn("job title", "[data-x]")
        assert len(store.candidates("job title")) == 1

    def test_mais_recente_entra_na_frente(self, store):
        store.learn("job title", "[data-antigo]")
        store.learn("job title", "[data-novo]")
        assert store.candidates("job title")[0] == "[data-novo]"

    def test_aprender_zera_falhas_de_cura(self, store):
        store.note_heal_attempt("job title", ok=False)
        store.learn("job title", "[data-x]")
        assert store.override("job title").heal_failures == 0


class TestContabilidade:
    def test_hit_sobe_e_zera_miss(self, store):
        store.learn("job title", "[data-x]")
        store.record_miss("job title")
        store.record_hit("job title", "[data-x]")
        candidato = store.override("job title").candidates[0]
        assert candidato.hits == 1
        assert candidato.misses == 0

    def test_ordena_por_saldo_de_acerto(self, store):
        store.learn("job title", "[data-a]")
        store.learn("job title", "[data-b]")
        for _ in range(3):
            store.record_hit("job title", "[data-a]")
        assert store.candidates("job title")[0] == "[data-a]"

    def test_miss_em_campo_sem_aprendido_nao_quebra(self, store):
        store.record_miss("campo inexistente")
        assert store.candidates("campo inexistente") == []

    def test_descarta_aprendido_que_errou_demais(self, store):
        """Senão o store vira cemitério: 1s de timeout por selector morto."""
        store.learn("job title", "[data-morto]")
        for _ in range(MAX_MISSES):
            store.record_miss("job title")
        removidos = store.prune()
        assert removidos == ["[data-morto]"]
        assert store.candidates("job title") == []

    def test_prune_poupa_quem_ainda_acerta(self, store):
        store.learn("job title", "[data-vivo]")
        for _ in range(MAX_MISSES - 1):
            store.record_miss("job title")
        assert store.prune() == []
        assert store.candidates("job title") == ["[data-vivo]"]


class TestCuraEIncuravel:
    def test_marca_incuravel_apos_limite(self, store):
        """Para de gastar LLM, mas o campo continua sendo reportado."""
        for _ in range(MAX_HEAL_FAILURES):
            override = store.note_heal_attempt("job title", ok=False)
        assert override.heal_failures == MAX_HEAL_FAILURES
        assert override.unhealable
        assert override.note

    def test_sucesso_zera_o_contador(self, store):
        store.note_heal_attempt("job title", ok=False)
        override = store.note_heal_attempt("job title", ok=True)
        assert override.heal_failures == 0
        assert not override.unhealable

    def test_cooldown_impede_insistencia(self):
        agora = datetime(2026, 9, 21, 12, 0, 0)
        recente = FieldOverride(
            last_heal_attempt=(agora - timedelta(hours=2)).isoformat()
        )
        antigo = FieldOverride(
            last_heal_attempt=(agora - timedelta(hours=30)).isoformat()
        )
        assert recente.in_cooldown(now=agora)
        assert not antigo.in_cooldown(now=agora)

    def test_sem_tentativa_nao_esta_em_cooldown(self):
        assert not FieldOverride().in_cooldown()

    def test_timestamp_corrompido_nao_bloqueia(self):
        """Doc estragado não pode travar a cura pra sempre."""
        assert not FieldOverride(last_heal_attempt="lixo").in_cooldown()


class TestPersistencia:
    def test_flush_grava_uma_vez_por_mudanca(self):
        repo = FakeRepo()
        store = SelectorStore(repo)
        store.learn("job title", "[data-x]")
        assert store.flush()
        assert repo.saves == 1

    def test_flush_sem_mudanca_nao_grava(self):
        """O resolver chama isso no fim de todo run, inclusive os sem cura."""
        repo = FakeRepo()
        store = SelectorStore(repo)
        assert not store.flush()
        assert repo.saves == 0

    def test_as_dict_omite_campo_sem_aprendido(self, store):
        store.learn("job title", "[data-x]")
        store.note_heal_attempt("outro campo", ok=False)
        assert store.as_dict() == {"job title": ["[data-x]"]}

    def test_le_doc_existente(self):
        repo = FakeRepo(
            {
                "version": 1,
                "fields": {
                    "job title": {
                        "candidates": [
                            {"sel": "[data-y]", "learned_at": "2026-09-01", "hits": 5}
                        ]
                    }
                },
            }
        )
        assert SelectorStore(repo).candidates("job title") == ["[data-y]"]

    def test_forget_apaga_o_campo(self, store):
        store.learn("job title", "[data-x]")
        assert store.forget("job title")
        assert not store.forget("job title")
        assert store.candidates("job title") == []
