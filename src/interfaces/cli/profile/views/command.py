import typer

from src.core.use_cases.profile_views_tracker import ProfileViewsTracker

_ARROW = {"subindo": "↑", "caindo": "↓", "estável": "→"}
_PACE = {"acelerando": "🚀", "desacelerando": "🐢", "ritmo constante": "➡️"}


def register_profile_views_commands(app: typer.Typer) -> None:
    @app.command("show")
    def show(window: int = typer.Option(7, help="Tamanho da janela em snapshots")):
        """Tendência e aceleração das visualizações do perfil (90 dias)."""
        a = ProfileViewsTracker().analyze(window=window)
        if a["samples"] == 0:
            print("📊 Sem snapshots ainda. Rode `engage` para capturar o 1º.")
            return
        print(f"📊 Visualizações do perfil (90d): {a['current']}")
        print(f"   amostras: {a['samples']}  (1ª: {a['first']})")
        if a["trend"] == "insuficiente":
            print("   tendência: dados insuficientes (precisa de ≥3 dias)")
            return
        arrow = _ARROW.get(a["trend"], "")
        pace = _PACE.get(a.get("pace", ""), "")
        print(
            f"   ritmo recente: {a['rate_recent']:+}/dia  "
            f"(anterior: {a['rate_prior']:+}/dia)"
        )
        print(f"   tendência: {arrow} {a['trend']}")
        print(f"   aceleração: {pace} {a.get('pace')} (Δritmo {a['accel']:+}/dia)")

    @app.command("list")
    def list_snaps():
        """Lista os snapshots diários crus."""
        snaps = ProfileViewsTracker().snapshots
        if not snaps:
            print("Sem snapshots.")
            return
        for s in snaps:
            print(f"  {s['date']}: {s['views']}")
