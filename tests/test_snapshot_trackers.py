"""Trackers de snapshot diário e a análise de tendência.

`ProfileViewsTracker.analyze` é a parte não-óbvia: a contagem do LinkedIn é um
total *rolante* de 90 dias, não cumulativo, então a análise compara o ritmo
(1ª derivada) e a aceleração (2ª) entre duas janelas — com um fatiamento
(`vals[-2*window:-window]`) que erra fácil.
"""

import pytest

from src.core.use_cases.profile_views_tracker import ProfileViewsTracker
from src.core.use_cases.search_appearances_tracker import SearchAppearancesTracker
from src.core.use_cases.ssi_tracker import SSITracker, _week_range


def _com_snapshots(tracker, pares):
    """Injeta histórico direto, sem passar por save() (que carimba hoje)."""
    tracker._data["snapshots"] = [{"date": data, **campos} for data, campos in pares]
    return tracker


@pytest.fixture
def views(tmp_path):
    return ProfileViewsTracker(tmp_path / "views.json")


@pytest.fixture
def appearances(tmp_path):
    return SearchAppearancesTracker(tmp_path / "appearances.json")


class TestPersistencia:
    def test_um_snapshot_por_dia_ultimo_vence(self, views):
        views.save(100)
        views.save(150)
        assert len(views.snapshots) == 1
        assert views.snapshots[0]["views"] == 150

    def test_already_captured_today(self, views):
        assert not views.already_captured_today()
        views.save(10)
        assert views.already_captured_today()

    def test_sobrevive_a_reabertura(self, tmp_path):
        caminho = tmp_path / "views.json"
        ProfileViewsTracker(caminho).save(42)
        assert ProfileViewsTracker(caminho).snapshots[0]["views"] == 42

    def test_json_corrompido_nao_derruba(self, tmp_path):
        caminho = tmp_path / "views.json"
        caminho.write_text("{lixo", encoding="utf-8")
        assert ProfileViewsTracker(caminho).snapshots == []

    def test_snapshots_ficam_em_ordem_cronologica(self, views):
        _com_snapshots(
            views, [("2026-03-10", {"views": 30}), ("2026-01-05", {"views": 10})]
        )
        assert [s["date"] for s in views.sorted_snapshots()] == [
            "2026-01-05",
            "2026-03-10",
        ]

    def test_snapshot_com_data_ilegivel_e_ignorado(self, views):
        _com_snapshots(
            views, [("2026-01-01", {"views": 1}), ("sem-data", {"views": 2})]
        )
        assert len(views.sorted_snapshots()) == 1


class TestProfileViewsAnalyze:
    def test_amostra_insuficiente(self, views):
        _com_snapshots(views, [("2026-01-01", {"views": 10})])
        assert views.analyze()["trend"] == "insuficiente"

    def test_ritmo_normaliza_buraco_no_historico(self, views):
        # +40 em 4 dias = 10/dia, mesmo sem snapshot nos dias do meio.
        _com_snapshots(
            views, [("2026-01-01", {"views": 100}), ("2026-01-05", {"views": 140})]
        )
        assert views._daily_rates()[0][1] == 10.0

    def test_tendencia_de_alta(self, views):
        _com_snapshots(
            views,
            [(f"2026-01-{d:02d}", {"views": 100 + d * 10}) for d in range(1, 11)],
        )
        resultado = views.analyze(window=3)
        assert resultado["trend"] == "subindo"
        assert resultado["rate_recent"] == 10.0

    def test_tendencia_de_queda(self, views):
        _com_snapshots(
            views,
            [(f"2026-01-{d:02d}", {"views": 200 - d * 5}) for d in range(1, 11)],
        )
        assert views.analyze(window=3)["trend"] == "caindo"

    def test_estavel_quando_o_valor_nao_muda(self, views):
        _com_snapshots(
            views, [(f"2026-01-{d:02d}", {"views": 100}) for d in range(1, 11)]
        )
        resultado = views.analyze(window=3)
        assert resultado["trend"] == "estável"
        assert resultado["pace"] == "ritmo constante"

    def test_aceleracao_positiva_quando_o_ritmo_cresce(self, views):
        # 5 taxas de 1/dia, depois 4 de 20/dia. Com window=3 a janela recente
        # pega só as rápidas e a anterior ainda alcança as lentas.
        lento = [(f"2026-01-{d:02d}", {"views": 100 + d}) for d in range(1, 7)]
        rapido = [
            (f"2026-01-{d:02d}", {"views": 106 + (d - 6) * 20}) for d in range(7, 11)
        ]
        _com_snapshots(views, lento + rapido)
        resultado = views.analyze(window=3)
        assert resultado["rate_recent"] == 20.0
        assert resultado["rate_prior"] < 20.0
        assert resultado["accel"] > 0
        assert resultado["pace"] == "acelerando"

    def test_desaceleracao(self, views):
        rapido = [(f"2026-01-{d:02d}", {"views": 100 + d * 20}) for d in range(1, 7)]
        lento = [(f"2026-01-{d:02d}", {"views": 220 + (d - 6)}) for d in range(7, 11)]
        _com_snapshots(views, rapido + lento)
        resultado = views.analyze(window=3)
        assert resultado["accel"] < 0
        assert resultado["pace"] == "desacelerando"

    def test_current_e_first_refletem_as_pontas(self, views):
        _com_snapshots(
            views,
            [
                ("2026-01-01", {"views": 10}),
                ("2026-01-02", {"views": 20}),
                ("2026-01-03", {"views": 30}),
            ],
        )
        resultado = views.analyze()
        assert (resultado["first"], resultado["current"]) == (10, 30)


class TestSearchAppearances:
    def test_sem_historico(self, appearances):
        assert appearances.analyze()["trend"] == "insuficiente"

    def test_delta_entre_os_dois_ultimos(self, appearances):
        _com_snapshots(
            appearances,
            [("2026-01-01", {"count": 10}), ("2026-01-02", {"count": 17})],
        )
        resultado = appearances.analyze()
        assert resultado["delta"] == 7
        assert resultado["trend"] == "subindo"

    def test_queda(self, appearances):
        _com_snapshots(
            appearances,
            [("2026-01-01", {"count": 20}), ("2026-01-02", {"count": 12})],
        )
        assert appearances.analyze()["trend"] == "caindo"


class TestSSI:
    def test_payload_do_scrape_e_preservado(self, tmp_path):
        tracker = SSITracker(tmp_path / "ssi.json")
        tracker.save({"total": 36.4, "brand": 10.25})
        snapshot = tracker.snapshots[0]
        assert snapshot["total"] == 36.4
        assert snapshot["brand"] == 10.25
        assert "date" in snapshot and "ts" in snapshot

    def test_lookup_por_semana(self, tmp_path):
        tracker = SSITracker(tmp_path / "ssi.json")
        inicio, fim = _week_range(2026, 10)
        _com_snapshots(
            tracker,
            [
                ((inicio.replace(day=inicio.day)).isoformat(), {"total": 30.0}),
                (fim.isoformat(), {"total": 35.0}),
            ],
        )
        assert tracker.latest_in_week(2026, 10)["total"] == 35.0

    def test_semana_sem_snapshot(self, tmp_path):
        tracker = SSITracker(tmp_path / "ssi.json")
        _com_snapshots(tracker, [("2026-01-05", {"total": 20.0})])
        assert tracker.latest_in_week(2026, 40) is None

    def test_week_range_comeca_na_segunda(self):
        inicio, fim = _week_range(2026, 10)
        assert inicio.weekday() == 0
        assert (fim - inicio).days == 6
