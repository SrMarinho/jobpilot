"""Travas do patch automático. O teste mais importante do projeto.

Um LLM com permissão de escrita no repositório é aceitável só enquanto estas
regras valerem. Elas não podem depender de o prompt ter sido bem escrito nem de
o modelo ter colaborado — é o motivo de o módulo ser puro e de este arquivo
existir.

O caso que resume tudo: um job cuja missão pede editar ``.env`` **tem que**
abortar na verificação de caminhos, antes de qualquer execução. Se este teste
não existir, o sistema não deve ser ligado.

E `pytest` importa o código do patch, ou seja, executa código de LLM — então a
ordem (caminhos antes de rodar nada) é parte da garantia, não detalhe de
implementação.
"""

import pytest

from src.core.use_cases.evolve.patch_policy import (
    BLOCKED_ENV,
    DISALLOWED_TOOLS,
    GLOBAL_FAILURE_THRESHOLD,
    MAX_DIFF_LINES,
    MAX_FILES,
    MAX_PATCHES_PER_DAY,
    branch_name,
    check_budget,
    check_diff,
    check_path,
    child_env,
    is_pushable,
    slug,
)


class TestDenylist:
    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            ".env.local",
            ".env.production",
            ".local/files/applied_jobs.json",
            ".local/jobpilot_drain_task.xml",
            ".local/startup_engage.ps1",
            ".local/reimport_tasks.ps1",
            ".github/workflows/ci.yml",
            "src/config/settings.py",
            "src/core/persistence/db.py",
            "src/core/persistence/keyed_repo.py",
            "src/utils/telegram.py",
            "src/bot/telegram_bot.py",
            "main.py",
            "src/interfaces/cli/router.py",
            "pyproject.toml",
            "uv.lock",
            ".pre-commit-config.yaml",
            ".gitignore",
            "CLAUDE.md",
        ],
    )
    def test_barra_o_que_nao_pode_ser_tocado(self, path):
        verdict = check_path(path)
        assert not verdict, f"{path} deveria ser proibido"
        assert "proibido por política" in verdict.reason

    @pytest.mark.parametrize(
        "path",
        [
            "src/core/use_cases/evolve/patch_policy.py",
            "src/core/use_cases/evolve/log_scan.py",
            "src/automation/evolve/healer.py",
            "src/automation/evolve/candidate_validator.py",
        ],
    )
    def test_o_evolve_nao_pode_patchear_os_proprios_guard_rails(self, path):
        """A denylist mora dentro de evolve/, então ela se protege."""
        assert not check_path(path)

    def test_denylist_vence_allowlist(self):
        """`src/core/use_cases/*.py` é permitido, mas evolve/ dentro dele não."""
        assert check_path("src/core/use_cases/goals_tracker.py")
        assert not check_path("src/core/use_cases/evolve/queue.py")

    @pytest.mark.parametrize(
        "path",
        [
            "../outro_repo/arquivo.py",
            "src/../../.env",
            "/etc/passwd",
            "C:/Windows/System32/x.dll",
            "C:\\Users\\dev\\.env",
        ],
    )
    def test_barra_fuga_do_repositorio(self, path):
        assert not check_path(path)

    @pytest.mark.parametrize("path", ["", "   "])
    def test_barra_caminho_vazio(self, path):
        assert not check_path(path)

    def test_barra_script_de_scheduler_em_qualquer_lugar(self):
        """Patch em task agendada ou não faz nada, ou derruba tudo em silêncio."""
        assert not check_path("scripts/qualquer.ps1")
        assert not check_path("algum/caminho/task.xml")


class TestAllowlist:
    @pytest.mark.parametrize(
        "path",
        [
            "src/automation/pages/people_search_page.py",
            "src/automation/pages/jobs_search_page.py",
            "src/core/use_cases/ssi_tracker.py",
            "src/core/use_cases/apply/easy_apply.py",
            "src/automation/tasks/connection_manager.py",
            "tests/test_selector_registry.py",
            "tests/fixtures/selectors/invite-modal.html",
            "docs/evolution.md",
        ],
    )
    def test_permite_o_que_a_cura_precisa(self, path):
        verdict = check_path(path)
        assert verdict, f"{path}: {verdict.reason}"

    @pytest.mark.parametrize(
        "path",
        [
            "src/interfaces/cli/apply/logic.py",
            "src/utils/logger.py",
            "README.md",
            "qualquer_coisa.py",
        ],
    )
    def test_nega_o_que_nao_foi_previsto(self, path):
        """Default é negar: allowlist não é sugestão."""
        verdict = check_path(path)
        assert not verdict
        assert "fora da allowlist" in verdict.reason


class TestCheckDiff:
    def test_aprova_patch_tipico_de_selector(self):
        assert check_diff(
            [
                "src/automation/pages/people_search_page.py",
                "tests/test_selector_registry.py",
            ],
            changed_lines=14,
        )

    def test_reprova_se_um_unico_caminho_e_proibido(self):
        """Basta um: o patch é tudo ou nada."""
        verdict = check_diff(
            ["src/automation/pages/jobs_search_page.py", ".env"], changed_lines=5
        )
        assert not verdict
        assert ".env" in verdict.reason
        assert len(verdict.rejected) == 1

    def test_reprova_patch_que_nao_mudou_nada(self):
        verdict = check_diff([])
        assert not verdict
        assert "não mudou arquivo nenhum" in verdict.reason

    def test_reprova_patch_espalhado(self):
        """Diff grande não é a correção pedida — é o modelo tendo ideias."""
        paths = [f"src/core/use_cases/t{i}.py" for i in range(MAX_FILES + 1)]
        verdict = check_diff(paths, changed_lines=10)
        assert not verdict
        assert f"máximo {MAX_FILES}" in verdict.reason

    def test_reprova_diff_longo(self):
        verdict = check_diff(
            ["src/core/use_cases/x.py"], changed_lines=MAX_DIFF_LINES + 1
        )
        assert not verdict
        assert "linhas alteradas" in verdict.reason

    def test_aceita_exatamente_no_limite(self):
        assert check_diff(
            [f"src/core/use_cases/t{i}.py" for i in range(MAX_FILES)],
            changed_lines=MAX_DIFF_LINES,
        )

    def test_aceita_barra_invertida_do_windows(self):
        """`git status` no Windows pode devolver caminho com barra invertida."""
        assert check_diff(["src\\automation\\pages\\jobs_search_page.py"])
        assert not check_diff(["src\\config\\settings.py"])


class TestBranch:
    def test_nome_previsivel(self):
        nome = branch_name("promote_selector", "invite modal", day="20260921")
        assert nome == "evolve/promote-selector-invite-modal-20260921"

    def test_slug_limpa_o_que_quebraria_o_git(self):
        assert slug("campo: 'invite modal'!") == "campo-invite-modal"
        assert slug("") == "job"
        assert slug("///") == "job"

    def test_slug_respeita_limite_sem_deixar_hifen_solto(self):
        resultado = slug("a" * 20 + "-" + "b" * 20, limit=21)
        assert len(resultado) <= 21
        assert not resultado.endswith("-")

    @pytest.mark.parametrize(
        "branch,esperado",
        [
            ("evolve/promote-selector-x-20260921", True),
            ("evolve/x", True),
            ("evolve/", False),
            ("master", False),
            ("main", False),
            ("", False),
            ("feature/evolve/x", False),
        ],
    )
    def test_so_branch_de_evolucao_e_empurravel(self, branch, esperado):
        assert is_pushable(branch) is esperado


class TestBudget:
    def _ok(self, **kwargs):
        base = dict(
            patches_today=0,
            patches_week=0,
            usd_today=0.0,
            open_branches=0,
        )
        base.update(kwargs)
        return check_budget(**base)

    def test_aprova_quando_tudo_esta_folgado(self):
        assert self._ok()

    def test_kill_switch_vence_tudo(self):
        """Quem desligou não quer saber de contagem."""
        verdict = self._ok(enabled=False, patches_today=0)
        assert not verdict
        assert "desligado" in verdict.reason

    def test_pausa_bloqueia(self):
        verdict = self._ok(paused=True)
        assert not verdict
        assert "pausado" in verdict.reason

    def test_cooldown_bloqueia(self):
        verdict = self._ok(in_cooldown=True)
        assert not verdict
        assert str(GLOBAL_FAILURE_THRESHOLD) in verdict.reason

    def test_teto_diario(self):
        verdict = self._ok(patches_today=MAX_PATCHES_PER_DAY)
        assert not verdict
        assert "teto diário de patches" in verdict.reason

    def test_teto_semanal(self):
        verdict = self._ok(patches_week=5)
        assert not verdict
        assert "teto semanal" in verdict.reason

    def test_teto_de_custo(self):
        verdict = self._ok(usd_today=1.0)
        assert not verdict
        assert "teto diário de custo" in verdict.reason

    def test_teto_de_branches_abertas(self):
        """Sem isto, um campo que quebra toda semana acumula branches."""
        verdict = self._ok(open_branches=3)
        assert not verdict
        assert "branches evolve/* abertas" in verdict.reason


class TestAmbienteDoAgente:
    def test_segredos_nao_chegam_ao_agente(self):
        entrada = {
            "PATH": "/usr/bin",
            "DATABASE_URL": "postgresql://user:senha@prod/db",
            "TELEGRAM_TOKEN": "123:abc",
            "DEEPSEEK_API_KEY": "sk-x",
            "USERPROFILE": "C:/Users/dev",
        }
        saida = child_env(entrada)
        assert "TELEGRAM_TOKEN" not in saida
        assert "DEEPSEEK_API_KEY" not in saida
        assert saida["PATH"] == "/usr/bin"
        assert saida["USERPROFILE"] == "C:/Users/dev"

    def test_database_url_fica_vazia_nao_ausente(self):
        """Vazia é o que faz a persistência cair no JSON local.

        Ausente deixaria um teste dos gates instanciar tracker apontando pro
        Postgres de produção, caso a variável vazasse de outro lugar.
        """
        saida = child_env({"DATABASE_URL": "postgresql://prod"})
        assert saida["DATABASE_URL"] == ""

    def test_todas_as_bloqueadas_sao_removidas(self):
        saida = child_env({k: "x" for k in BLOCKED_ENV})
        assert [k for k in BLOCKED_ENV if k != "DATABASE_URL" and k in saida] == []

    def test_bash_nunca_e_permitido_ao_agente(self):
        """Sem Bash ele não roda git, não instala nada e não sai pra rede."""
        assert "Bash" in DISALLOWED_TOOLS
        assert "WebFetch" in DISALLOWED_TOOLS
        assert "WebSearch" in DISALLOWED_TOOLS
