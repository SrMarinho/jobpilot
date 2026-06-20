import typer

from src.core.use_cases.goals_tracker import GoalsTracker, GOAL_KEYS


def register_goals_commands(app: typer.Typer) -> None:
    @app.command("show")
    def show_goals():
        """Mostra as metas semanais configuradas."""
        goals = GoalsTracker().all()
        print("🎯 Metas semanais:")
        for k in GOAL_KEYS:
            print(f"  • {k}: {goals[k]}")

    @app.command("set")
    def set_goal(
        key: str = typer.Argument(..., help=f"Uma de: {', '.join(GOAL_KEYS)}"),
        value: int = typer.Argument(..., help="Alvo semanal"),
    ):
        """Define a meta semanal de uma métrica."""
        try:
            GoalsTracker().set(key, value)
        except ValueError as e:
            print(f"❌ {e}")
            return
        print(f"✅ Meta '{key}' = {value}")
