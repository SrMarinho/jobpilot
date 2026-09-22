"""Fila que separa a cura (no browser) do patch (sem browser).

O que se testa aqui é sobretudo o dedupe e a morte de job. Sem dedupe, um
selector que é curado em três runs seguidos abre três branches pro mesmo
problema. Sem morte, um job que não passa nos gates é retentado pra sempre,
queimando LLM a cada hora do drain.
"""

import pytest

from src.core.use_cases.evolve.queue import (
    KIND_PATCH_BUG,
    KIND_PROMOTE_SELECTOR,
    MAX_ATTEMPTS,
    STATUS_DEAD,
    STATUS_DONE,
    STATUS_FAILED,
    EvolutionQueue,
)


class FakeRepo:
    def __init__(self):
        self.data = {}

    def load(self):
        return self.data

    def save(self, data):
        self.data = data


@pytest.fixture
def fila():
    return EvolutionQueue(FakeRepo())


def _promote(fila, field="job title", selector="[data-x]"):
    return fila.enqueue(
        KIND_PROMOTE_SELECTOR, {"field": field, "selector": selector}, sig="abc123"
    )


class TestEnqueue:
    def test_enfileira_e_fica_pendente(self, fila):
        job = _promote(fila)
        assert job is not None
        assert fila.pending() and fila.pending()[0].id == job.id

    def test_tipo_desconhecido_e_erro_de_programacao(self, fila):
        with pytest.raises(ValueError):
            fila.enqueue("tipo_inventado", {})

    def test_nao_duplica_job_equivalente(self, fila):
        """Três curas do mesmo selector não podem abrir três branches."""
        assert _promote(fila) is not None
        assert _promote(fila) is None
        assert len(fila.all()) == 1

    def test_selector_diferente_e_outro_job(self, fila):
        _promote(fila, selector="[data-a]")
        assert _promote(fila, selector="[data-b]") is not None

    def test_nao_reenfileira_o_que_ja_foi_concluido(self, fila):
        job = _promote(fila)
        fila.mark_done(job.id)
        assert _promote(fila) is None

    def test_dedupe_de_patch_usa_a_assinatura(self, fila):
        fila.enqueue(KIND_PATCH_BUG, {"x": 1}, sig="sig-1")
        assert fila.enqueue(KIND_PATCH_BUG, {"x": 2}, sig="sig-1") is None
        assert fila.enqueue(KIND_PATCH_BUG, {"x": 3}, sig="sig-2") is not None


class TestExecucao:
    def test_next_job_devolve_um_por_vez(self, fila):
        """Um por drain: o Agendador corta o drain por tempo."""
        _promote(fila, selector="[data-a]")
        _promote(fila, selector="[data-b]")
        assert fila.next_job().payload["selector"] == "[data-a]"

    def test_fila_vazia_devolve_none(self, fila):
        assert fila.next_job() is None

    def test_running_conta_tentativa(self, fila):
        job = _promote(fila)
        fila.mark_running(job.id, base_sha="deadbeef")
        atualizado = fila.get(job.id)
        assert atualizado.attempts == 1
        assert atualizado.base_sha == "deadbeef"

    def test_falha_volta_pra_fila_uma_vez(self, fila):
        job = _promote(fila)
        fila.mark_running(job.id)
        assert fila.mark_failed(job.id, "ruff reprovou").status == STATUS_FAILED
        assert fila.next_job() is not None

    def test_esgotar_tentativas_mata_o_job(self, fila):
        """Job que não passa nos gates não vai passar na terceira."""
        job = _promote(fila)
        for _ in range(MAX_ATTEMPTS):
            fila.mark_running(job.id)
            fila.mark_failed(job.id, "pytest reprovou")
        assert fila.get(job.id).status == STATUS_DEAD
        assert fila.next_job() is None

    def test_erro_e_truncado(self, fila):
        job = _promote(fila)
        fila.mark_failed(job.id, "x" * 900)
        assert len(fila.get(job.id).last_error) == 500

    def test_falha_de_job_inexistente_nao_quebra(self, fila):
        assert fila.mark_failed("nao-existe", "erro") is None

    def test_counts_resume_o_estado(self, fila):
        a = _promote(fila, selector="[data-a]")
        _promote(fila, selector="[data-b]")
        fila.mark_done(a.id)
        assert fila.counts()[STATUS_DONE] == 1


class TestHistorico:
    def test_purge_mantem_os_ultimos(self, fila):
        for i in range(8):
            job = _promote(fila, selector=f"[data-{i}]")
            fila.mark_done(job.id)
        assert fila.purge_finished(keep=3) == 5
        assert len(fila.all()) == 3

    def test_purge_nao_toca_em_pendente(self, fila):
        """Pendente descartado seria trabalho perdido em silêncio."""
        for i in range(5):
            job = _promote(fila, selector=f"[data-{i}]")
            fila.mark_done(job.id)
        pendente = _promote(fila, selector="[data-vivo]")
        fila.purge_finished(keep=1)
        assert any(j.id == pendente.id for j in fila.all())

    def test_purge_sem_excesso_nao_faz_nada(self, fila):
        job = _promote(fila)
        fila.mark_done(job.id)
        assert fila.purge_finished(keep=50) == 0

    def test_purge_preserva_a_ordem(self, fila):
        ids = []
        for i in range(5):
            job = _promote(fila, selector=f"[data-{i}]")
            fila.mark_done(job.id)
            ids.append(job.id)
        fila.purge_finished(keep=2)
        assert [j.id for j in fila.all()] == ids[-2:]


class TestPersistencia:
    def test_estado_sobrevive_a_releitura(self):
        repo = FakeRepo()
        job = _promote(EvolutionQueue(repo))
        assert EvolutionQueue(repo).get(job.id).payload["selector"] == "[data-x]"

    def test_doc_vazio_nao_quebra(self):
        assert EvolutionQueue(FakeRepo()).all() == []
