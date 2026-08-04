"""Extração do ID da vaga a partir da URL — a chave de deduplicação.

Se `_job_id` mudar de resposta pra mesma vaga, o bot se candidata de novo a
algo que já aplicou. Cada job board tem seu formato de URL.
"""

import pytest

from src.core.entities.applied_job import AppliedJob, RejectedJob
from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    import src.core.use_cases.applied_jobs_tracker as module

    monkeypatch.setattr(module, "APPLIED_JOBS_FILE", tmp_path / "applied.json")
    monkeypatch.setattr(module, "REJECTED_JOBS_FILE", tmp_path / "rejected.json")
    return AppliedJobsTracker()


class TestJobId:
    @pytest.mark.parametrize(
        "url,esperado",
        [
            ("https://www.linkedin.com/jobs/view/4181234567/", "4181234567"),
            (
                "https://www.linkedin.com/jobs/search/?currentJobId=987654321",
                "987654321",
            ),
            ("https://br.indeed.com/viewjob?jk=abc123def456", "abc123def456"),
            ("https://br.indeed.com/rc/clk?jk=xyz789&from=serp", "xyz789"),
            ("glassdoor://job/555", "gd_555"),
        ],
    )
    def test_formatos_conhecidos(self, tracker, url, esperado):
        assert tracker._job_id(url) == esperado

    def test_url_desconhecida_vira_slug_sanitizado(self, tracker):
        job_id = tracker._job_id("https://vagas.example.com/Vaga-Dev?ref=1")
        assert job_id == "https___vagas_example_com_vaga_dev_ref_1"
        assert len(job_id) <= 80

    def test_slug_e_truncado_em_80(self, tracker):
        assert len(tracker._job_id("https://x.com/" + "a" * 300)) == 80

    def test_query_string_nao_muda_o_id_do_linkedin(self, tracker):
        base = "https://www.linkedin.com/jobs/view/4181234567/"
        assert tracker._job_id(base) == tracker._job_id(f"{base}?refId=abc&trk=xyz")

    def test_id_e_estavel_para_a_mesma_url(self, tracker):
        url = "https://vagas.example.com/x"
        assert tracker._job_id(url) == tracker._job_id(url)


class TestDedup:
    def test_marcar_aplicada_impede_reaplicacao(self, tracker, monkeypatch):
        monkeypatch.setattr(
            "src.core.use_cases.applied_jobs_tracker.send_telegram",
            lambda *a, **k: None,
        )
        url = "https://www.linkedin.com/jobs/view/111/"
        assert not tracker.already_applied(url)
        tracker.mark_applied(url, "Dev Backend", salary=8000, site="linkedin")
        assert tracker.already_applied(url)

    def test_rejeitada_nao_conta_como_aplicada(self, tracker):
        url = "https://www.linkedin.com/jobs/view/222/"
        tracker.mark_rejected(url, "Dev PHP", reason="stack", site="linkedin")
        assert tracker.already_rejected(url)
        assert not tracker.already_applied(url)


class TestEntities:
    def test_record_bate_com_as_colunas_de_applied_jobs(self):
        job = AppliedJob.create("1", "http://x", "Dev", salary=9000, site="linkedin")
        assert set(job.as_record()) == {
            "job_id",
            "title",
            "company",
            "url",
            "applied_at",
            "salary_offered",
            "level",
            "site",
            "contract",
        }

    def test_record_bate_com_as_colunas_de_rejected_jobs(self):
        job = RejectedJob.create("1", "http://x", "Dev", reason="stack")
        assert set(job.as_record()) == {
            "job_id",
            "title",
            "url",
            "rejected_at",
            "reason",
            "site",
        }

    def test_document_omite_a_chave_primaria(self):
        job = AppliedJob.create("1", "http://x", "Dev")
        assert "job_id" not in job.as_document()
        assert job.as_document()["title"] == "Dev"

    def test_campos_vazios_viram_unknown(self):
        job = AppliedJob.create("1", "http://x", "Dev", level="", site="", contract="")
        assert job.level == job.site == job.contract == "unknown"
