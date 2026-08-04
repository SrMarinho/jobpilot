"""Parsing dos posts de anúncio de contratação (feature `jobs hired`).

A recência vem do token relativo do LinkedIn ("há 2 semanas"), não de uma data —
se `post_age_days` errar, o benchmark mistura contratação velha com recente.
"""

import pytest

from src.core.use_cases.hired_posts import (
    is_hire_announcement,
    matches_role,
    post_age_days,
)


class TestPostAgeDays:
    @pytest.mark.parametrize(
        "texto,esperado",
        [
            ("há 3 h", 0),
            ("há 45 min", 0),
            ("há 5 d", 5),
            ("há 2 sem", 14),
            ("há 3 meses", 90),
        ],
    )
    def test_unidades(self, texto, esperado):
        assert post_age_days(texto) == esperado

    def test_sem_token_de_idade(self):
        assert post_age_days("Post sem marcação temporal") is None

    def test_texto_vazio(self):
        assert post_age_days("") is None


class TestIsHireAnnouncement:
    def test_anuncio_de_contratacao(self):
        assert is_hire_announcement(
            "Feliz em compartilhar que comecei uma nova posição como "
            "Desenvolvedor de Software na Empresa X!"
        )

    def test_quem_procura_vaga_nao_conta(self):
        # O filtro de "seeking" tem precedência: quem procura não foi contratado.
        assert not is_hire_announcement(
            "Estou disponível para novas oportunidades como desenvolvedor. "
            "Alguém tem uma vaga? Me indica!"
        )

    def test_post_qualquer(self):
        assert not is_hire_announcement("Escrevi um artigo sobre testes em Python.")


class TestMatchesRole:
    def test_casa_por_palavra_do_cargo(self):
        assert matches_role(
            "Comecei como Desenvolvedor Backend",
            "Engenheiro de Software",
            "Desenvolvedor",
        )

    def test_casa_pela_headline(self):
        assert matches_role(
            "Nova etapa!", "Desenvolvedor de Software Pleno", "Desenvolvedor"
        )

    def test_cargo_sem_relacao(self):
        assert not matches_role(
            "Comecei como Analista Contábil", "Contador", "Desenvolvedor"
        )

    def test_cargo_vazio_aceita_tudo(self):
        assert matches_role("qualquer coisa", "qualquer headline", "")
