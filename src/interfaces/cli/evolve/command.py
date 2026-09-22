"""Comandos de autoevolução. Nesta fase o evolve só OBSERVA — não age.

``scan`` lê os logs, agrupa falha recorrente em incidente e mostra o que está
apodrecendo há dias sem ninguém notar. É de propósito o primeiro passo: antes
de deixar o sistema se consertar sozinho, é preciso ver se ele concorda com o
seu julgamento sobre o que está quebrado.
"""

import typer
from rich.console import Console
from rich.table import Table

from src.config.settings import log_dir, logger
from src.core.use_cases.evolve.incident_store import IncidentStore
from src.core.use_cases.evolve.log_scan import (
    CHRONIC_MIN_COUNT,
    CHRONIC_MIN_DAYS,
    DEFAULT_WINDOW_DAYS,
    Incident,
    is_chronic,
    scan,
)

console = Console()


def register_evolve_commands(app: typer.Typer) -> None:
    @app.command("scan")
    def cmd_scan(
        days: int = typer.Option(
            DEFAULT_WINDOW_DAYS, "--days", help="Janela de dias a analisar"
        ),
        min_count: int = typer.Option(
            CHRONIC_MIN_COUNT, "--min-count", help="Ocorrências para ser crônico"
        ),
        min_days: int = typer.Option(
            CHRONIC_MIN_DAYS, "--min-days", help="Dias distintos para ser crônico"
        ),
        level: str = typer.Option("WARNING", "--level", help="Nível mínimo"),
        show_all: bool = typer.Option(
            False, "--all", help="Mostra todos os incidentes, não só os crônicos"
        ),
        limit: int = typer.Option(20, "--limit", help="Máximo de linhas na tabela"),
        telegram: bool = typer.Option(False, "--telegram", help="Manda no Telegram"),
        scheduled: bool = typer.Option(
            False, "--scheduled", help="Modo agendado: só avisa se houver crônico"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Não grava nada no store de incidentes"
        ),
    ):
        """Agrupa falhas recorrentes dos logs em incidentes. Não age em nada."""
        incidents, stats = scan(
            log_dir,
            days=days,
            min_level=level.upper(),
            min_count=min_count,
            min_days=min_days,
        )

        store = None if dry_run else IncidentStore()
        novos = 0
        if store is not None:
            novos = store.record(incidents)
            visiveis = store.actionable(incidents)
        else:
            visiveis = incidents

        cronicos = [
            i for i in visiveis if is_chronic(i, min_count=min_count, min_days=min_days)
        ]
        mostrar = visiveis if show_all else cronicos

        _render(
            mostrar[:limit],
            stats,
            days,
            novos,
            silenciados=len(incidents) - len(visiveis),
        )

        if telegram and (cronicos or not scheduled):
            from src.utils.telegram import send_telegram

            send_telegram(_as_telegram(cronicos, days), topic="alerts")

        if cronicos:
            logger.warning(
                f"[evolve] {len(cronicos)} incidente(s) crônico(s) em {days}d"
            )

    @app.command("incidents")
    def cmd_incidents(
        show_all: bool = typer.Option(
            False, "--all", help="Inclui os silenciados (ignorado/resolvido/aposentado)"
        ),
    ):
        """Estado persistido de cada assinatura já vista."""
        states = IncidentStore().all_states()
        if not show_all:
            states = [s for s in states if not s.silenced()]
        if not states:
            console.print("[yellow]Nenhum incidente registrado.[/yellow]")
            return
        table = Table(title=f"Incidentes registrados — {len(states)}")
        table.add_column("Sig")
        table.add_column("Status")
        table.add_column("Até")
        table.add_column("Tent.")
        table.add_column("Template")
        for state in states:
            table.add_row(
                state.sig,
                state.status,
                state.suppress_until or "—",
                str(state.attempts),
                state.template[:60],
            )
        console.print(table)

    @app.command("ignore")
    def cmd_ignore(
        sig: str = typer.Argument(..., help="Assinatura mostrada pelo scan"),
        days: int = typer.Option(30, "--days", help="Por quantos dias calar"),
        note: str = typer.Option("", "--note", help="Motivo (aparece em incidents)"),
    ):
        """Marca um incidente como ruído — para de aparecer no scan."""
        state = IncidentStore().ignore(sig, days=days, note=note)
        console.print(
            f"[green]{sig} silenciado até {state.suppress_until}.[/green] "
            f"Volta a aparecer depois disso se continuar acontecendo."
        )


def _render(
    incidents: list[Incident],
    stats,
    days: int,
    novos: int,
    *,
    silenciados: int,
) -> None:
    # As órfãs entram no cabeçalho de propósito: log perdido num sistema que
    # decide sozinho não pode ser detalhe escondido.
    console.print(
        f"[dim]{stats.files} arquivo(s) · {stats.records} registro(s) · "
        f"{stats.orphan_lines} linha(s) de continuação/rasgo · "
        f"{stats.incidents} assinatura(s) · {novos} nova(s) · "
        f"{silenciados} silenciada(s)[/dim]"
    )
    if not incidents:
        console.print(
            f"[green]Nenhum incidente crônico em {days} dias.[/green] "
            "(use --all para ver os esporádicos)"
        )
        return

    table = Table(title=f"Incidentes — janela de {days} dias")
    table.add_column("Sig")
    table.add_column("Qtd", justify="right")
    table.add_column("Dias", justify="right")
    table.add_column("Nível")
    table.add_column("Task")
    table.add_column("Campo")
    table.add_column("Mensagem")
    for incident in incidents:
        cronico = is_chronic(incident)
        table.add_row(
            incident.sig,
            f"[red]{incident.count}[/red]" if cronico else str(incident.count),
            str(incident.days_seen),
            incident.level,
            ",".join(sorted(incident.tasks)),
            ",".join(sorted(incident.fields)) or "—",
            incident.template[:70],
        )
    console.print(table)
    console.print(
        "[dim]Campo preenchido = falha de selector, candidata a cura. "
        "Sem campo = precisa diagnóstico.[/dim]"
    )


def _as_telegram(cronicos: list[Incident], days: int) -> str:
    if not cronicos:
        return f"✅ <b>Evolve scan</b>: nenhum incidente crônico em {days} dias."
    linhas = "\n".join(
        f"• <code>{i.sig}</code> <b>{i.count}×</b> em {i.days_seen}d "
        f"[{','.join(sorted(i.tasks))}]\n  {_escape(i.template[:90])}"
        for i in cronicos[:10]
    )
    extra = f"\n\n<i>+{len(cronicos) - 10} outros</i>" if len(cronicos) > 10 else ""
    return (
        f"🔁 <b>Evolve scan</b>: {len(cronicos)} incidente(s) crônico(s) "
        f"em {days} dias\n\n{linhas}{extra}"
    )


def _escape(text: str) -> str:
    import html

    return html.escape(text)
