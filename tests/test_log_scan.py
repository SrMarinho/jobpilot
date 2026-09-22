"""O parser de log é a base de tudo que o evolve decide sozinho.

Se ele agrupar errado, o sistema autônomo age no alvo errado — ou pior, age no
ruído e deixa a quebra real passar. Por isso os casos aqui são **linhas reais**
de ``logs/2026/09/``, não amostras inventadas:

- ``campo=invite modal`` — 711 ocorrências em 2 variantes de mensagem; tem que
  virar **um** incidente, senão o diagnóstico gasta LLM duas vezes no mesmo
  problema (e, sem a normalização de blob citado, viriam ~700 incidentes).
- SSI descontinuado — o crônico que nenhum selector conserta.
- Escrita rasgada e bloco ``Call log:`` do Playwright — o log de verdade não é
  uma linha por registro, ao contrário do que o nome ``SingleLineFormatter``
  sugere (ele só está no handler de console).
"""

from datetime import date, datetime

import pytest

from src.core.use_cases.evolve.log_scan import (
    Incident,
    extract_field,
    group_incidents,
    is_chronic,
    merge_by_field,
    normalize,
    parse_lines,
    signature,
    template_of,
)

# Linhas reais, copiadas de logs/2026/09/.
INVITE_SEM_SUFIXO = (
    "2026-09-10 19:46:53,052 - [7a386537] - [connect] - WARNING - "
    "campo=invite modal: nenhum candidato casou após o Connect — "
    "selector pode ter mudado"
)
INVITE_COM_SUFIXO = (
    "2026-09-21 19:15:26,790 - [7bbe5716] - [connect] - WARNING - "
    "campo=invite modal: nenhum candidato casou após o Connect — selector pode "
    "ter mudado; página: '0 notificação Pular para pesquisa Pular para conteúdo "
    "principal Início 1 Minha rede Vagas Mensagens 23 Notificações Eu'"
)
SSI = (
    "2026-09-21 19:36:43,839 - [9061e50a] - [engage] - WARNING - "
    "SSI scrape falhou (pilares incompletos: {}; "
    "url=https://www.linkedin.com/sales/ssi); text head: 'Lista de ações Seu "
    "Social Selling Index atual Você não tem acesso ao SSI foi descontinuado'"
)
INFO_LINE = (
    "2026-09-21 19:36:47,082 - [9061e50a] - [engage] - INFO - "
    "Profile views scraped: 121 (90d)"
)


def _record(line: str):
    records, _ = parse_lines([line])
    assert records, f"linha não parseou: {line[:60]}"
    return records[0]


class TestParseLines:
    def test_campos_do_cabecalho(self):
        record = _record(INVITE_SEM_SUFIXO)
        assert record.ts == datetime(2026, 9, 10, 19, 46, 53)
        assert record.run_id == "7a386537"
        assert record.task == "connect"
        assert record.level == "WARNING"
        assert record.msg.startswith("campo=invite modal")
        assert record.day == date(2026, 9, 10)

    def test_escrita_rasgada_e_colada_no_registro_anterior(self):
        """Processos concorrentes partem a linha no meio da palavra.

        "Postgres pool aberto" virou "Postgres p" + "ool aberto" em 124 linhas
        de setembro. Colar reconstrói a mensagem; descartar perderia o registro
        inteiro, não só o pedaço.
        """
        linhas = [
            "2026-09-21 19:37:02,047 - [6e8404e1] - [profile-capture] - INFO - "
            "Postgres p",
            "ool aberto",
        ]
        records, orphans = parse_lines(linhas)
        assert orphans == 1
        assert len(records) == 1
        assert records[0].msg == "Postgres p ool aberto"

    def test_bloco_multilinha_do_playwright_fica_num_registro(self):
        linhas = [
            "2026-09-19 12:00:00,000 - [abc12345] - [apply] - ERROR - "
            "Error extracting job 7: Locator.scroll_into_view_if_needed: Timeout",
            "Call log:",
            "  - waiting for element to be visible, enabled and stable",
            "  - done scrolling",
        ]
        records, orphans = parse_lines(linhas)
        assert orphans == 3
        assert len(records) == 1
        assert "Call log:" in records[0].msg
        assert "done scrolling" in records[0].msg

    def test_continuacao_antes_do_primeiro_cabecalho_e_descartada(self):
        """Arquivo que começa no meio de um registro rasgado não tem dono."""
        records, orphans = parse_lines(["ool aberto", INVITE_SEM_SUFIXO])
        assert orphans == 1
        assert len(records) == 1
        assert records[0].msg.startswith("campo=invite modal")

    def test_linha_lixo_nao_quebra_o_parser(self):
        records, orphans = parse_lines(["", "   ", "\x00sujeira"])
        assert records == []
        assert orphans == 3


class TestNormalize:
    def test_blob_citado_longo_colapsa(self):
        """Sem isto, a MESMA falha renderia ~700 assinaturas distintas.

        O head de innerText da página muda a cada run (contador de
        notificações, mensagens), então ele não pode entrar na assinatura.
        """
        assert "'<text>'" in normalize(_record(INVITE_COM_SUFIXO).msg)
        assert "Pular para pesquisa" not in normalize(_record(INVITE_COM_SUFIXO).msg)

    def test_texto_citado_curto_sobrevive(self):
        """Nome de modelo entre aspas é identidade da falha, não ruído."""
        assert "'claude-fable-5'" in normalize("LLM: modelo 'claude-fable-5' caiu")

    @pytest.mark.parametrize(
        "bruto,esperado",
        [
            ("Opening https://www.linkedin.com/sales/ssi now", "Opening <url> now"),
            ("post urn:li:activity:7123456789 ok", "post <id> ok"),
            ("job 7891234567 falhou", "job <id> falhou"),
            ("Engajou 1/15 posts", "Engajou 1/<n> posts"),
            ("capturado em 2026-09-21 19:36:43", "capturado em <ts>"),
            ("lendo C:\\Users\\dev\\resume.pdf", "lendo <path>"),
        ],
    )
    def test_partes_variaveis_viram_placeholder(self, bruto, esperado):
        assert normalize(bruto) == esperado

    def test_campo_sobrevive_a_normalizacao(self):
        """`campo=X` é o elo entre incidente e constante de page."""
        assert "campo=invite modal" in normalize(_record(INVITE_COM_SUFIXO).msg)

    def test_template_e_truncado(self):
        assert len(template_of("x" * 500)) == 120


class TestSignature:
    def test_duas_ocorrencias_da_mesma_falha_batem(self):
        a = _record(INVITE_SEM_SUFIXO)
        b = _record(INVITE_SEM_SUFIXO.replace("19:46:53", "20:10:11"))
        assert signature(a.level, a.task, a.msg) == signature(b.level, b.task, b.msg)

    def test_task_diferente_nao_bate(self):
        """SSI falha no engage e no profile-capture; são runs diferentes."""
        assert signature(
            "WARNING", "engage", "SSI scrape returned no data"
        ) != signature("WARNING", "profile-capture", "SSI scrape returned no data")

    def test_nivel_diferente_nao_bate(self):
        assert signature("WARNING", "connect", "x") != signature(
            "ERROR", "connect", "x"
        )


class TestExtractField:
    @pytest.mark.parametrize(
        "msg,esperado",
        [
            ("campo=invite modal: nenhum candidato casou", "invite modal"),
            ("Selector não resolveu: campo='job title' (3 candidatos)", "job title"),
            (
                'Botão não resolveu: campo="send invite button" — mudou',
                "send invite button",
            ),
            ("Feed exhausted — no more new posts", None),
        ],
    )
    def test_extrai_nome_do_campo(self, msg, esperado):
        assert extract_field(msg) == esperado


class TestGroupAndChronic:
    def test_agrupa_e_conta_dias(self):
        linhas = [
            INVITE_SEM_SUFIXO,
            INVITE_SEM_SUFIXO.replace("2026-09-10", "2026-09-11"),
            INVITE_SEM_SUFIXO.replace("2026-09-10", "2026-09-11"),
        ]
        records, _ = parse_lines(linhas)
        incidents = group_incidents(records)
        assert len(incidents) == 1
        assert incidents[0].count == 3
        assert incidents[0].days_seen == 2
        assert incidents[0].fields == {"invite modal"}
        assert len(incidents[0].samples) == 2

    def test_info_e_filtrado_por_nivel_no_read(self):
        """`parse_lines` não filtra — o corte por nível é do `read_records`."""
        records, _ = parse_lines([INFO_LINE])
        assert records[0].level == "INFO"

    def test_ordena_do_mais_frequente(self):
        records, _ = parse_lines([INVITE_SEM_SUFIXO, INVITE_SEM_SUFIXO, SSI])
        incidents = group_incidents(records)
        assert incidents[0].count == 2
        assert incidents[1].count == 1

    @pytest.mark.parametrize(
        "count,dias,esperado",
        [
            (711, 15, True),  # invite modal real
            (10, 3, True),  # exatamente no limite
            (9, 3, False),  # volume insuficiente
            (100, 2, False),  # tempestade de uma noite (rede caída), não crônico
            (1, 1, False),
        ],
    )
    def test_cronico_exige_volume_e_persistencia(self, count, dias, esperado):
        incident = Incident(sig="x", level="WARNING", task="connect", template="t")
        incident.count = count
        incident.days = {date(2026, 9, d + 1) for d in range(dias)}
        assert is_chronic(incident) is esperado


class TestMergeByField:
    def test_variantes_do_mesmo_campo_fundem(self):
        """O caso real: 707 sem sufixo + 4 com sufixo = 711, um incidente."""
        linhas = [INVITE_SEM_SUFIXO] * 3 + [INVITE_COM_SUFIXO]
        records, _ = parse_lines(linhas)
        assert len(group_incidents(records)) == 2, "duas assinaturas, como esperado"

        merged = merge_by_field(group_incidents(records))
        assert len(merged) == 1
        assert merged[0].count == 4
        assert merged[0].fields == {"invite modal"}
        # O template que sobrevive é o da variante dominante.
        assert "página" not in merged[0].template

    def test_incidente_sem_campo_nao_funde(self):
        """Sem o nome do campo não há evidência de que seja o mesmo problema."""
        records, _ = parse_lines([SSI, SSI.replace("engage", "profile-capture")])
        merged = merge_by_field(group_incidents(records))
        assert len(merged) == 2

    def test_campos_diferentes_nao_fundem(self):
        outro = INVITE_SEM_SUFIXO.replace("campo=invite modal", "campo=job title")
        records, _ = parse_lines([INVITE_SEM_SUFIXO, outro])
        merged = merge_by_field(group_incidents(records))
        assert len(merged) == 2

    def test_dias_e_janela_sao_unidos(self):
        a = INVITE_SEM_SUFIXO
        b = INVITE_COM_SUFIXO.replace("2026-09-21", "2026-09-25")
        records, _ = parse_lines([a, a, b])
        merged = merge_by_field(group_incidents(records))
        assert merged[0].days_seen == 2
        assert merged[0].first_seen == datetime(2026, 9, 10, 19, 46, 53)
        assert merged[0].last_seen == datetime(2026, 9, 25, 19, 15, 26)
