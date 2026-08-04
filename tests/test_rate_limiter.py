"""Quotas proativas, circuit breaker e o guard de run.

O ponto da mudança: parar **antes** do LinkedIn reclamar, e valer igual pra
CLI, bot e agendador.
"""

from datetime import date, datetime, timedelta

import pytest

from src.core.persistence.doc_repo import DocRepo
from src.core.use_cases.rate_limiter import FAILURE_THRESHOLD, RateLimiter
from src.core.use_cases.run_guard import check_run, within_active_hours


@pytest.fixture
def limiter(tmp_path):
    return RateLimiter(
        repo=DocRepo("rate_limits_test", json_file=tmp_path / "limits.json"),
        today=date(2026, 3, 10),  # uma terça-feira
    )


class TestContagem:
    def test_comeca_zerado(self, limiter):
        assert limiter.used_today("connect") == 0
        assert limiter.allows("connect")

    def test_record_incrementa(self, limiter):
        limiter.record("connect")
        limiter.record("connect", amount=2)
        assert limiter.used_today("connect") == 3

    def test_acoes_sao_contadas_separadamente(self, limiter):
        limiter.record("connect", amount=5)
        assert limiter.used_today("apply") == 0

    def test_remaining_reflete_o_uso(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "10")
        limiter.record("connect", amount=4)
        assert limiter.remaining_today("connect") == 6


class TestQuota:
    def test_barra_ao_atingir_o_teto_diario(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "3")
        limiter.record("connect", amount=3)
        status = limiter.check("connect")
        assert not status
        assert "diário" in status.reason

    def test_libera_abaixo_do_teto(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "3")
        limiter.record("connect", amount=2)
        assert limiter.allows("connect")

    def test_teto_semanal_soma_os_dias_da_semana(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "100")
        monkeypatch.setenv("LIMIT_CONNECT_WEEK", "10")
        repo = DocRepo("rate_limits_test", json_file=tmp_path / "limits.json")
        # Segunda e terça da mesma semana.
        RateLimiter(repo=repo, today=date(2026, 3, 9)).record("connect", amount=6)
        limiter = RateLimiter(repo=repo, today=date(2026, 3, 10))
        limiter.record("connect", amount=4)
        assert limiter.used_this_week("connect") == 10
        assert not limiter.check("connect")

    def test_semana_anterior_nao_conta(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_WEEK", "10")
        repo = DocRepo("rate_limits_test", json_file=tmp_path / "limits.json")
        RateLimiter(repo=repo, today=date(2026, 3, 2)).record("connect", amount=9)
        limiter = RateLimiter(repo=repo, today=date(2026, 3, 10))
        assert limiter.used_this_week("connect") == 0

    def test_teto_zero_desliga_o_limite(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "0")
        monkeypatch.setenv("LIMIT_CONNECT_WEEK", "0")
        limiter.record("connect", amount=9999)
        assert limiter.allows("connect")
        assert limiter.remaining_today("connect") == -1


class TestCircuitBreaker:
    def test_sem_cooldown_por_padrao(self, limiter):
        assert limiter.cooldown_reason() is None

    def test_open_cooldown_bloqueia(self, limiter):
        limiter.open_cooldown("checkpoint")
        assert "checkpoint" in limiter.cooldown_reason()

    def test_reset_libera(self, limiter):
        limiter.open_cooldown("checkpoint")
        limiter.clear_cooldown()
        assert limiter.cooldown_reason() is None

    def test_cooldown_expirado_se_limpa_sozinho(self, limiter):
        passado = (datetime.now() - timedelta(hours=1)).isoformat()
        limiter._data["cooldown"] = {"until": passado, "reason": "velho"}
        assert limiter.cooldown_reason() is None

    def test_falhas_seguidas_abrem_o_breaker(self, limiter):
        for _ in range(FAILURE_THRESHOLD - 1):
            assert not limiter.record_failure("connect")
        assert limiter.record_failure("connect", "erro")
        assert limiter.cooldown_reason() is not None

    def test_sucesso_zera_o_contador(self, limiter):
        for _ in range(FAILURE_THRESHOLD - 1):
            limiter.record_failure("connect")
        limiter.record_success("connect")
        # Recomeça do zero: o breaker é sobre falha *consecutiva*.
        assert not limiter.record_failure("connect")
        assert limiter.cooldown_reason() is None


class TestJanelaHoraria:
    def test_dentro_da_janela(self, monkeypatch):
        monkeypatch.setenv("ACTIVE_HOURS", "07:00-23:00")
        assert within_active_hours(datetime(2026, 3, 10, 12, 0))

    def test_fora_da_janela(self, monkeypatch):
        monkeypatch.setenv("ACTIVE_HOURS", "07:00-23:00")
        assert not within_active_hours(datetime(2026, 3, 10, 4, 0))

    def test_janela_que_cruza_a_meia_noite(self, monkeypatch):
        monkeypatch.setenv("ACTIVE_HOURS", "22:00-06:00")
        assert within_active_hours(datetime(2026, 3, 10, 23, 30))
        assert within_active_hours(datetime(2026, 3, 10, 2, 0))
        assert not within_active_hours(datetime(2026, 3, 10, 12, 0))

    def test_valor_invalido_nao_bloqueia(self, monkeypatch):
        monkeypatch.setenv("ACTIVE_HOURS", "lixo")
        assert within_active_hours(datetime(2026, 3, 10, 4, 0))


class TestCheckRun:
    def test_libera_no_caminho_feliz(self, limiter):
        assert check_run("connect", limiter=limiter)

    def test_cooldown_barra_ate_com_force(self, limiter):
        limiter.open_cooldown("checkpoint")
        # Force pula quota e janela, mas nunca o breaker: insistir depois de um
        # checkpoint é exatamente o que não se deve fazer.
        assert not check_run("connect", limiter=limiter, force=True)

    def test_force_pula_a_quota(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "1")
        limiter.record("connect")
        assert not check_run("connect", limiter=limiter)
        assert check_run("connect", limiter=limiter, force=True)

    def test_janela_so_vale_para_agendado(self, limiter, monkeypatch):
        monkeypatch.setenv("ACTIVE_HOURS", "07:00-23:00")
        madrugada = datetime(2026, 3, 10, 4, 0)
        assert check_run("connect", limiter=limiter, now=madrugada)
        assert not check_run("connect", limiter=limiter, scheduled=True, now=madrugada)

    def test_motivo_da_quota_chega_no_verdict(self, limiter, monkeypatch):
        monkeypatch.setenv("LIMIT_CONNECT_DAY", "1")
        limiter.record("connect")
        assert "diário" in check_run("connect", limiter=limiter).reason
