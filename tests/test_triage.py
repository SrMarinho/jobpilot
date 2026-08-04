"""Triagem de vaga avulsa: reconhecimento de URL e normalização de layout."""

import pytest

from src.automation.tasks.job_triage import TriageResult, readable_url
from src.bot.urls import extract_job_url, is_job_url
from src.core.entities.eval_result import EvalResult


class TestIsJobUrl:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.linkedin.com/jobs/view/4441633388/",
            "https://www.linkedin.com/jobs/search/?currentJobId=4441633388",
            "https://br.indeed.com/viewjob?jk=abc123",
            "https://br.indeed.com/rc/clk?jk=xyz&from=serp",
        ],
    )
    def test_links_de_vaga(self, url):
        assert is_job_url(url)

    @pytest.mark.parametrize(
        "texto",
        [
            # Busca não é vaga: triar isso avaliaria a página errada.
            "https://www.linkedin.com/jobs/search/?keywords=dev",
            "https://www.linkedin.com/in/alguem/",
            "https://www.linkedin.com/feed/",
            "bom dia, tudo certo?",
            "",
            "linkedin.com/jobs/view/123",  # sem esquema
        ],
    )
    def test_nao_e_vaga(self, texto):
        assert not is_job_url(texto)

    def test_extrai_url_no_meio_do_texto(self):
        texto = "olha essa https://www.linkedin.com/jobs/view/999/ que achei"
        assert extract_job_url(texto) == "https://www.linkedin.com/jobs/view/999/"

    def test_sem_url_devolve_none(self):
        assert extract_job_url("nenhum link aqui") is None


class TestReadableUrl:
    def test_converte_jobs_view_para_o_painel_de_busca(self):
        # /jobs/view/ é montada com classes hashadas; o painel da busca é o
        # layout que os selectors sabem ler.
        assert (
            readable_url("https://www.linkedin.com/jobs/view/4441633388/")
            == "https://www.linkedin.com/jobs/search/?currentJobId=4441633388"
        )

    def test_ignora_query_string_extra(self):
        url = "https://www.linkedin.com/jobs/view/123/?refId=abc&trk=xyz"
        assert readable_url(url).endswith("currentJobId=123")

    def test_url_de_outro_site_passa_intacta(self):
        url = "https://br.indeed.com/viewjob?jk=abc"
        assert readable_url(url) == url

    def test_url_ja_no_formato_de_busca_nao_muda(self):
        url = "https://www.linkedin.com/jobs/search/?currentJobId=123"
        assert readable_url(url) == url


class TestTriageResultMensagem:
    def test_erro_vira_aviso(self):
        msg = TriageResult(
            url="http://x", site="linkedin", error="deu ruim"
        ).as_telegram()
        assert "Triagem falhou" in msg and "deu ruim" in msg

    def test_match_mostra_salario_e_gaps(self):
        triage = TriageResult(
            url="http://x",
            site="linkedin",
            title="Dev Python",
            company="Empresa",
            result=EvalResult(
                matches=True,
                salary=9000,
                reason="stack bate",
                missing_skills=["redis", "celery"],
                contract="CLT",
            ),
        )
        msg = triage.as_telegram()
        assert "Match" in msg
        assert "9.000" in msg and "(CLT)" in msg
        assert "redis" in msg and "celery" in msg

    def test_nao_match(self):
        triage = TriageResult(
            url="http://x",
            site="linkedin",
            title="Dev PHP",
            result=EvalResult(matches=False, reason="stack errada"),
        )
        msg = triage.as_telegram()
        assert "Não bate" in msg and "stack errada" in msg

    def test_avisa_quando_veio_do_cache(self):
        triage = TriageResult(
            url="http://x",
            site="linkedin",
            result=EvalResult(matches=True),
            from_cache=True,
        )
        assert "reaproveitada" in triage.as_telegram()

    def test_ok_exige_resultado(self):
        assert not TriageResult(url="x", site="linkedin").ok
        assert TriageResult(url="x", site="linkedin", result=EvalResult()).ok
