import typer

from src.core.use_cases.ssi_tracker import SSITracker


def register_profile_ssi_commands(app: typer.Typer) -> None:
    @app.command("show")
    def cmd_show():
        """Mostra o SSI atual e breakdown por pilar."""
        tracker = SSITracker()
        snaps = tracker._data.get("snapshots", [])
        if not snaps:
            typer.echo("No SSI snapshots yet. Run `profile capture` first.")
            return
        latest = snaps[-1]
        typer.echo(f"SSI Score: {latest.get('total', '?')}/100  ({latest.get('date', '?')})")
        typer.echo(f"  Brand professional:  {latest.get('brand', '?')}/25")
        typer.echo(f"  Find right people:   {latest.get('find_people', '?')}/25")
        typer.echo(f"  Engage with insights:{latest.get('engage_insights', '?')}/25")
        typer.echo(f"  Build relationships: {latest.get('relationships', '?')}/25")
        if "rank_industry_pct" in latest:
            typer.echo(f"  Industry rank: top {latest['rank_industry_pct']}%")
        if "rank_network_pct" in latest:
            typer.echo(f"  Network rank:  top {latest['rank_network_pct']}%")

    @app.command("list")
    def cmd_list():
        """Lista histórico de snapshots SSI."""
        tracker = SSITracker()
        snaps = tracker._data.get("snapshots", [])
        if not snaps:
            typer.echo("No SSI snapshots yet.")
            return
        typer.echo(f"{'Date':<12} {'Total':>6} {'Brand':>6} {'People':>7} {'Insights':>9} {'Rels':>5}")
        typer.echo("-" * 52)
        for s in snaps:
            typer.echo(
                f"  {s.get('date','?'):<10} "
                f"{s.get('total','?'):>6} "
                f"{s.get('brand','?'):>6} "
                f"{s.get('find_people','?'):>7} "
                f"{s.get('engage_insights','?'):>9} "
                f"{s.get('relationships','?'):>5}"
            )
