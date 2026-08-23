"""Na página de vaga individual o LinkedIn 2026 não tem <h1> e as classes são
ofuscadas; o <title> da aba virou a única âncora do título."""

import pytest

from src.automation.pages.jobs_search_page import title_from_tab_text


@pytest.mark.parametrize(
    "raw,esperado",
    [
        (
            "Desenvolvedor Web Pleno - Remoto | Grupo Impetus | LinkedIn",
            "Desenvolvedor Web Pleno - Remoto",
        ),
        # O "|" do proprio nome da vaga nao pode truncar o titulo.
        (
            "Desenvolvedor Python | Django - Pleno | Framework Digital | LinkedIn",
            "Desenvolvedor Python | Django - Pleno",
        ),
        (
            "Python Backend Developer (Remote) | Hire Feed | LinkedIn",
            "Python Backend Developer (Remote)",
        ),
    ],
)
def test_tira_empresa_e_sufixo_linkedin(raw, esperado):
    assert title_from_tab_text(raw) == esperado


def test_aba_sem_o_formato_esperado_usa_o_primeiro_segmento():
    assert title_from_tab_text("Alguma coisa") == "Alguma coisa"


@pytest.mark.parametrize("raw", ["LinkedIn", "", "   "])
def test_aba_sem_titulo_de_vaga_devolve_vazio(raw):
    assert title_from_tab_text(raw) == ""
