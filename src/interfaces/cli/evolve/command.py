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
        once_a_day: bool = typer.Option(
            False,
            "--once-a-day",
            help="Sai sem fazer nada se já rodou hoje (para o drain horário)",
        ),
    ):
        """Agrupa falhas recorrentes dos logs em incidentes. Não age em nada."""
        if once_a_day:
            # O drain roda de hora em hora. Sem esta trava, um crônico que
            # persiste (e é da natureza dele persistir) geraria 24 mensagens
            # por dia no Telegram — o alerta viraria ruído e pararia de ser
            # lido, que é o modo de falha que este sistema existe pra evitar.
            from src.interfaces.cli.persistence import (
                is_already_ran_today,
                save_ran_today,
            )

            if is_already_ran_today("evolve-scan"):
                logger.info("[evolve] scan já rodou hoje — saindo")
                return
            save_ran_today("evolve-scan")

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

    @app.command("queue")
    def cmd_queue():
        """Fila de trabalho: o que a cura pediu e o drain ainda não fez."""
        from src.core.use_cases.evolve.queue import EvolutionQueue

        fila = EvolutionQueue()
        jobs = fila.all()
        if not jobs:
            console.print("[yellow]Fila vazia.[/yellow]")
            return
        table = Table(title=f"Fila da evolução — {fila.counts()}")
        table.add_column("Job")
        table.add_column("Tipo")
        table.add_column("Status")
        table.add_column("Tent.")
        table.add_column("Assunto")
        table.add_column("Último erro")
        for job in jobs:
            table.add_row(
                job.id,
                job.kind,
                job.status,
                str(job.attempts),
                str(job.payload.get("field") or job.sig or "—"),
                (job.last_error or "")[:50],
            )
        console.print(table)

    @app.command("drain")
    def cmd_drain(
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Roda os gates sem chamar o agente de patch"
        ),
    ):
        """Executa um job da fila em worktree isolado. Sem browser.

        Um por execução: o drain agendado tem teto de tempo no Agendador, e um
        patch pode levar minutos entre LLM, ruff, pytest e smoke.
        """
        from src.core.use_cases.evolve.patcher import Patcher

        result = Patcher(dry_run=dry_run).drain_one()
        if result is None:
            console.print("[dim]Nada a fazer.[/dim]")
            return

        cor = "green" if result.ok else "red"
        console.print(
            f"[{cor}]{'Patch aplicado' if result.ok else 'Patch reprovado'}[/{cor}]"
        )
        for step in result.steps:
            marca = "[green]✓[/green]" if step.ok else "[red]✗[/red]"
            console.print(
                f"  {marca} {step.name}"
                + (f" — {step.detail[:90]}" if step.detail else "")
            )
        if result.branch:
            console.print(
                f"Branch: [cyan]{result.branch}[/cyan]"
                + ("" if result.pushed else " (não empurrada)")
            )
        if not result.ok:
            raise typer.Exit(code=1)

    @app.command("status")
    def cmd_status():
        """Orçamento, freios e kill switches da evolução."""
        import os

        from src.core.use_cases.evolve.evolve_state import EvolveState
        from src.core.use_cases.evolve.patcher import (
            evolve_enabled,
            open_evolve_branches,
            push_enabled,
        )
        from src.core.use_cases.evolve.queue import EvolutionQueue

        snap = EvolveState().snapshot()
        cura = os.getenv("EVOLVE_HEAL", "false")
        table = Table(title="Estado da autoevolução")
        table.add_column("Item")
        table.add_column("Valor")
        for item, valor in (
            ("cura in-run (EVOLVE_HEAL)", cura),
            ("patch (EVOLVE_ENABLED)", str(evolve_enabled())),
            ("push (EVOLVE_PUSH)", str(push_enabled())),
            ("pausado", str(snap.paused)),
            ("em cooldown", f"{snap.in_cooldown} ({snap.cooldown_until or '—'})"),
            ("falhas seguidas", str(snap.consecutive_failures)),
            ("patches hoje", str(snap.patches_today)),
            ("patches na semana", str(snap.patches_week)),
            ("custo hoje", f"US$ {snap.usd_today:.4f}"),
            ("branches evolve/* abertas", str(len(open_evolve_branches()))),
            ("fila", str(EvolutionQueue().counts() or "vazia")),
        ):
            table.add_row(item, valor)
        console.print(table)

    @app.command("pause")
    def cmd_pause(
        off: bool = typer.Option(False, "--off", help="Retoma em vez de pausar"),
    ):
        """Kill switch do patch, sem precisar mexer no .env."""
        from src.core.use_cases.evolve.evolve_state import EvolveState

        state = EvolveState()
        state.pause(not off)
        console.print(
            "[green]Evolução retomada.[/green]"
            if off
            else "[yellow]Evolução pausada.[/yellow] Nenhum patch será aplicado."
        )

    @app.command("reset-cooldown")
    def cmd_reset_cooldown():
        """Zera o cooldown aberto por falhas seguidas de gate."""
        from src.core.use_cases.evolve.evolve_state import EvolveState

        EvolveState().clear_cooldown()
        console.print("[green]Cooldown zerado.[/green]")


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
