"""Leitura do diff e contadores do patch — as partes puras do patcher.

O caso que este arquivo existe para travar: ``git status --porcelain`` **esconde
arquivo que está no .gitignore**, e ``.env`` está lá. Sem ``--ignored=matching``
um agente que escrevesse ``.env`` passava invisível pelo gate de caminhos. Isso
foi verificado na prática: o gate aprovou um worktree com ``.env`` escrito, e
só reprovou depois, por outro motivo.

Como a flag vive na chamada do git e não numa função pura, o que se testa aqui
é o parser recebendo a saída que ela produz — incluindo as linhas `!!` que só
aparecem com a flag ligada.
"""

import pytest

from src.core.use_cases.evolve.evolve_state import EvolveState
from src.core.use_cases.evolve.patch_policy import check_diff
from src.core.use_cases.evolve.patcher import _changed_paths, _cost_of


class FakeRepo:
    def __init__(self):
        self.data = {}

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


class TestChangedPaths:
    def test_le_modificado_e_novo(self):
        saida = " M src/automation/pages/jobs_search_page.py\n?? tests/test_novo.py\n"
        assert _changed_paths(saida) == [
            "src/automation/pages/jobs_search_page.py",
            "tests/test_novo.py",
        ]

    def test_le_arquivo_ignorado(self):
        """`!!` só aparece com --ignored=matching. É a linha que pega o .env."""
        saida = "!! .env\n!! .local/files/applied_jobs.json\n"
        paths = _changed_paths(saida)
        assert paths == [".env", ".local/files/applied_jobs.json"]

    def test_env_escrito_pelo_agente_e_reprovado(self):
        """O teste de ataque, na forma que roda sem git."""
        paths = _changed_paths("!! .env\n M src/core/use_cases/goals_tracker.py\n")
        verdict = check_diff(paths, changed_lines=3)
        assert not verdict
        assert ".env" in verdict.reason

    def test_renomeado_usa_o_destino(self):
        saida = "R  antigo.py -> src/core/use_cases/novo.py\n"
        assert _changed_paths(saida) == ["src/core/use_cases/novo.py"]

    def test_remove_aspas_de_caminho_com_espaco(self):
        saida = '?? "src/core/use_cases/com espaco.py"\n'
        assert _changed_paths(saida) == ["src/core/use_cases/com espaco.py"]

    @pytest.mark.parametrize("saida", ["", "\n", "x\n"])
    def test_saida_vazia_ou_curta_nao_quebra(self, saida):
        assert _changed_paths(saida) == []


class TestCusto:
    def test_le_custo_do_json(self):
        assert _cost_of('{"total_cost_usd": 0.0421, "num_turns": 6}') == 0.0421

    def test_aceita_nome_alternativo(self):
        assert _cost_of('{"cost_usd": 0.1}') == 0.1

    @pytest.mark.parametrize(
        "saida", ["", "não é json", "[]", '{"outra": 1}', '{"total_cost_usd": "abc"}']
    )
    def test_custo_ilegivel_e_zero(self, saida):
        """Custo ilegível não pode virar exceção nem número inventado."""
        assert _cost_of(saida) == 0.0


class TestEvolveState:
    def test_conta_patch_mesmo_quando_falha(self):
        """O custo do LLM já aconteceu; contar só sucesso furaria o teto."""
        state = EvolveState(FakeRepo())
        state.record_patch(usd=0.05)
        state.record_patch(usd=0.05)
        assert state.patches_today() == 2
        assert state.usd_today() == pytest.approx(0.10)

    def test_falhas_seguidas_abrem_cooldown(self):
        state = EvolveState(FakeRepo())
        assert state.record_gate_failure() == 1
        assert not state.in_cooldown()
        state.record_gate_failure()
        state.record_gate_failure()
        assert state.in_cooldown()

    def test_sucesso_zera_o_freio(self):
        state = EvolveState(FakeRepo())
        for _ in range(3):
            state.record_gate_failure()
        state.record_gate_success()
        assert not state.in_cooldown()
        assert state.snapshot().consecutive_failures == 0

    def test_cooldown_corrompido_nao_trava_pra_sempre(self):
        repo = FakeRepo()
        repo.data = {"cooldown_until": "lixo"}
        assert not EvolveState(repo).in_cooldown()

    def test_anti_loop_por_assinatura_e_commit(self):
        """Mesmo problema sobre o mesmo código: uma tentativa, pra sempre."""
        state = EvolveState(FakeRepo())
        assert not state.already_attempted("sig1", "abc123")
        state.record_attempt("sig1", "abc123")
        assert state.already_attempted("sig1", "abc123")
        assert not state.already_attempted("sig1", "outro-commit")

    def test_sem_assinatura_nao_registra(self):
        state = EvolveState(FakeRepo())
        state.record_attempt(None, "abc")
        assert not state.already_attempted(None, "abc")

    def test_pausa_e_retomada(self):
        state = EvolveState(FakeRepo())
        state.pause()
        assert state.snapshot().paused
        state.pause(False)
        assert not state.snapshot().paused
