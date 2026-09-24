from src.core.use_cases.presence_index import (
    METRICS,
    PILLARS,
    baseline,
    metric_score,
    score,
)


def test_pesos_de_cada_pilar_somam_um():
    for parts in PILLARS.values():
        assert abs(sum(w for _, w in parts) - 1) < 1e-9


def test_semana_na_media_da_metade_de_cada_pilar():
    semana = {m: 10 for m in METRICS}
    idx = score(semana, baseline([semana, semana]))
    assert all(idx[p] == 12.5 for p in PILLARS)
    assert idx["total"] == 50.0


def test_dobro_da_media_da_nota_cheia_e_nao_passa_disso():
    base = {m: 10.0 for m in METRICS}
    assert score({m: 20 for m in METRICS}, base)["total"] == 100.0
    assert score({m: 500 for m in METRICS}, base)["total"] == 100.0


def test_semana_parada_zera():
    assert score({m: 0 for m in METRICS}, {m: 10.0 for m in METRICS})["total"] == 0.0


def test_sem_historico_atividade_vale_media_e_nao_nota_cheia():
    assert metric_score(3, None) == 0.5
    assert metric_score(3, 0) == 0.5
    assert metric_score(0, None) == 0.0


def test_baseline_vazio():
    assert baseline([]) == {}


def test_metrica_nao_medida_fica_fora_da_media():
    base = baseline([{"views": 100}, {"views": None}, {}])
    assert base["views"] == 100


def test_metrica_nao_medida_na_semana_e_neutra():
    base = {"views": 100.0, "posts": 2.0}
    idx = score({"views": None, "posts": 2}, base)
    assert idx["brand"] == 12.5
