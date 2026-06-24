import typer

from src.core.use_cases.search_appearances_tracker import SearchAppearancesTracker

_ARROW = {"subindo": "↑", "caindo": "↓", "estável": "→", "insuficiente": "?"}


def register_profile_appearances_commands(app: typer.Typer) -> None:
    @app.command("show")
    def cmd_show():
        """Mostra aparições em pesquisa: valor atual e tendência."""
        tracker = SearchAppearancesTracker()
        a = tracker.analyze()
        if a["samples"] == 0:
            typer.echo("No search-appearance snapshots yet. Run `profile capture` first.")
            return
        arrow = _ARROW.get(a["trend"], "?")
        typer.echo(f"Search appearances (last ~7d): {a['current']}")
        if a["previous"] is not None:
            typer.echo(f"  Previous: {a['previous']}  Δ {a['delta']:+}  {arrow} {a['trend']}")
        else:
            typer.echo("  (only 1 snapshot — need ≥2 for trend)")

    @app.command("list")
    def cmd_list():
        """Lista histórico de snapshots de aparições em pesquisa."""
        tracker = SearchAppearancesTracker()
        snaps = tracker.snapshots
        if not snaps:
            typer.echo("No snapshots yet.")
            return
        for s in snaps:
            typer.echo(f"  {s['date']}: {s['count']}")
