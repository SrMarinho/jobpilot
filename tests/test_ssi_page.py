"""O SSI devolveu {} todo dia desde 2026-06-25 — parsing, não carregamento.

O parser antigo só aceitava "<valor> <rótulo>" na mesma linha. Estes testes
fixam as duas ordens e a proteção contra o gráfico de comparação com pares.
"""

from src.automation.pages.ssi_page import parse_ssi_text

# Layout 2026: valor em linha própria, ANTES do rótulo, e o bloco de comparação
# repetindo os mesmos rótulos com as médias do setor/rede.
PAGINA_VALOR_ANTES = (
    "Social Selling Index\n"
    "Seu Social Selling Index\n"
    "24,08\n"
    "8,38\n"
    "Estabelecer sua marca profissional\n"
    "6,10\n"
    "Localizar as pessoas certas\n"
    "1,00\n"
    "Interagir oferecendo insights\n"
    "8,60\n"
    "Criar relacionamentos\n"
    "Classificação no setor\n"
    "Primeiros 83%\n"
    "Classificação na rede\n"
    "Primeiros 90%\n"
    "Média do setor: Estabelecer sua marca profissional 20,00\n"
    "Média da rede: Criar relacionamentos 22,00\n"
)

# Layout antigo/EN: rótulo primeiro, valor depois.
PAGINA_VALOR_DEPOIS = (
    "Social Selling Index\n"
    "Establish your professional brand\t7.50\n"
    "Find the right people\t5.00\n"
    "Engage with insights\t2.25\n"
    "Build relationships\t9.00\n"
)


def test_le_os_quatro_pilares_com_valor_antes_do_rotulo():
    r = parse_ssi_text(PAGINA_VALOR_ANTES)
    assert r["brand"] == 8.38
    assert r["find_people"] == 6.1
    assert r["engage_insights"] == 1.0
    assert r["relationships"] == 8.6


def test_le_os_quatro_pilares_com_valor_depois_do_rotulo():
    r = parse_ssi_text(PAGINA_VALOR_DEPOIS)
    assert r["brand"] == 7.5
    assert r["find_people"] == 5.0
    assert r["engage_insights"] == 2.25
    assert r["relationships"] == 9.0


def test_ignora_as_medias_do_grafico_de_comparacao():
    # 20,00 e 22,00 são médias de pares e ficariam acima do teto de 25 por
    # pouco — o descarte tem que vir do rótulo, não do valor.
    r = parse_ssi_text(PAGINA_VALOR_ANTES)
    assert r["brand"] != 20.0
    assert r["relationships"] != 22.0


def test_le_as_duas_classificacoes_percentuais():
    r = parse_ssi_text(PAGINA_VALOR_ANTES)
    assert r["rank_industry_pct"] == 83
    assert r["rank_network_pct"] == 90


def test_pagina_errada_devolve_none():
    assert parse_ssi_text("Página não encontrada") is None


def test_wording_novo_em_um_pilar_nao_zera_os_outros():
    # All-or-nothing era o que descartava a captura inteira; o parser devolve
    # o parcial e quem decide o corte é o scrape().
    texto = PAGINA_VALOR_ANTES.replace("Interagir oferecendo insights", "Interagir")
    r = parse_ssi_text(texto)
    assert "engage_insights" not in r
    assert r["brand"] == 8.38
