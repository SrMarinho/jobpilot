"""Funil da vaga: avaliada → aprovada → aplicada.

A distância entre aprovada e aplicada é o número que interessa — muita
aprovada parada significa gargalo no envio, não na busca.
"""

import pytest

from src.core.use_cases.report.metrics import MetricsCalculator
from src.core.use_cases.report.period import WeekPeriod


class FakeRepo:
    """Repositório de mentira — o funil só lê, então dict basta."""

    def __init__(self, evaluated: dict | None = None, applied: dict | None = None):
        self._evaluated = evaluated or {}
        self._applied = applied or {}

    def evaluated(self) -> dict:
        return self._evaluated

    def applied(self) -> dict:
        return self._applied


PERIODO = WeekPeriod(2026, 10)


def _dentro_do_periodo() -> str:
    return PERIODO.range[0].isoformat() + "T12:00:00"


def _job(matches: bool, site: str = "linkedin", quando: str | None = None) -> dict:
    return {
        "matches": matches,
        "site": site,
        "evaluated_at": quando or _dentro_do_periodo(),
    }


class TestJobFunnel:
    def test_sem_dados(self):
        funnel = MetricsCalculator(FakeRepo()).job_funnel(PERIODO)
        assert funnel["evaluated"] == 0
        assert funnel["approval_rate"] == 0.0

    def test_contagem_e_taxas(self):
        repo = FakeRepo(
            evaluated={
                "1": _job(True),
                "2": _job(True),
                "3": _job(False),
                "4": _job(False),
            },
            applied={"1": {"applied_at": _dentro_do_periodo()}},
        )
        funnel = MetricsCalculator(repo).job_funnel(PERIODO)
        assert funnel["evaluated"] == 4
        assert funnel["approved"] == 2
        assert funnel["applied"] == 1
        assert funnel["approval_rate"] == 50.0
        assert funnel["apply_rate"] == 50.0

    def test_pendentes_sao_aprovadas_sem_candidatura(self):
        repo = FakeRepo(
            evaluated={"1": _job(True), "2": _job(True), "3": _job(True)},
            applied={"1": {"applied_at": _dentro_do_periodo()}},
        )
        assert MetricsCalculator(repo).job_funnel(PERIODO)["pending"] == 2

    def test_pendentes_nunca_fica_negativo(self):
        # Aplicadas de semanas anteriores podem passar do total aprovado desta.
        repo = FakeRepo(
            evaluated={"1": _job(True)},
            applied={
                "1": {"applied_at": _dentro_do_periodo()},
                "2": {"applied_at": _dentro_do_periodo()},
                "3": {"applied_at": _dentro_do_periodo()},
            },
        )
        assert MetricsCalculator(repo).job_funnel(PERIODO)["pending"] == 0

    def test_fora_do_periodo_nao_conta(self):
        repo = FakeRepo(
            evaluated={"1": _job(True), "2": _job(True, quando="2020-01-01T00:00:00")}
        )
        assert MetricsCalculator(repo).job_funnel(PERIODO)["evaluated"] == 1

    def test_quebra_por_site(self):
        repo = FakeRepo(
            evaluated={
                "1": _job(True, site="linkedin"),
                "2": _job(False, site="linkedin"),
                "3": _job(True, site="indeed"),
            }
        )
        por_site = MetricsCalculator(repo).job_funnel(PERIODO)["by_site"]
        assert por_site["linkedin"] == {"evaluated": 2, "approved": 1}
        assert por_site["indeed"] == {"evaluated": 1, "approved": 1}

    def test_site_ausente_vira_unknown(self):
        repo = FakeRepo(
            evaluated={"1": {"matches": True, "evaluated_at": _dentro_do_periodo()}}
        )
        assert "unknown" in MetricsCalculator(repo).job_funnel(PERIODO)["by_site"]

    def test_apply_rate_sem_aprovadas_nao_divide_por_zero(self):
        repo = FakeRepo(evaluated={"1": _job(False)})
        assert MetricsCalculator(repo).job_funnel(PERIODO)["apply_rate"] == 0.0


class TestRenderDoFunil:
    @pytest.fixture
    def formatter(self):
        from src.core.use_cases.report.formatter import ReportFormatter

        return ReportFormatter()

    def test_funil_vazio_nao_renderiza_secao(self, formatter):
        assert formatter._job_funnel_block(None) == ""
        assert formatter._job_funnel_block({"evaluated": 0}) == ""

    def test_render_mostra_as_tres_etapas(self, formatter):
        bloco = formatter._job_funnel_block(
            {
                "evaluated": 10,
                "approved": 4,
                "applied": 3,
                "approval_rate": 40.0,
                "apply_rate": 75.0,
                "pending": 1,
                "by_site": {"linkedin": {"evaluated": 10, "approved": 4}},
            }
        )
        assert "Avaliadas: 10" in bloco
        assert "Aprovadas: 4" in bloco
        assert "Aplicadas: 3" in bloco
        assert "Na fila: 1" in bloco
        assert "linkedin: 4/10" in bloco
