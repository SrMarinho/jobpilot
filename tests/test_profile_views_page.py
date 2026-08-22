"""O scraper devolveu None em 163 runs seguidos; o texto real da página é o
único regressor confiável para o parsing."""

import re

import pytest

from src.automation.pages.profile_views_page import _PATTERNS, _to_int

# Wording LinkedIn 2026 (PT-BR), como sai de document.body.innerText: o rótulo
# aparece três vezes e só a terceira ocorrência tem o número colado.
REAL_PAGE_PT = (
    "Início Minha rede Vagas Mensagens 24 Notificações Eu Para negócios\n"
    "Acesse o Premium novamente\n"
    "Quem viu seu perfil\n"
    "Últimos 90 dias\n"
    "126\n"
    "Quem viu seu perfil nos últimos 90 dias\n"
    "3 recrutadores\n"
    "Saiba quem viu seu perfil, candidate-se a vagas personalizadas\n"
)


def _extract(text: str) -> int | None:
    low = text.lower()
    for pat in _PATTERNS:
        for m in re.finditer(pat, low):
            val = _to_int(m.group(1))
            if val is not None:
                return val
    return None


def test_le_a_contagem_do_texto_real_da_pagina():
    assert _extract(REAL_PAGE_PT) == 126


def test_nao_confunde_a_janela_de_90_dias_com_a_contagem():
    assert _extract("Quem viu seu perfil\nÚltimos 90 dias\n7\n") != 90


@pytest.mark.parametrize(
    "text,esperado",
    [
        ("1.234 visualizações do perfil", 1234),
        ("Visualizações do perfil\n88", 88),
        ("512 profile views", 512),
        ("2.048 who viewed your profile", 2048),
    ],
)
def test_variantes_de_wording(text, esperado):
    assert _extract(text) == esperado


def test_sem_numero_devolve_none():
    assert _extract("Quem viu seu perfil nos últimos 90 dias") is None
