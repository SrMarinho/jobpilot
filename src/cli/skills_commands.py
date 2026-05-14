from typing import Optional

import typer

from src.cli.skills_logic import run_skills_list, run_skills_top, run_skills_clear


def register_skills_commands(skills_app: typer.Typer) -> None:
    from src.cli.enums import SkillCategory

    @skills_app.command("list")
    def skills_list(
        category: Optional[SkillCategory] = typer.Option(None, "--category", help="Filter by category"),
        level: Optional[int] = typer.Option(None, "--level", min=1, max=5, help="Filter by learning level (1=fast, 5=slow)"),
    ):
        """List all missing skills sorted by frequency."""
        run_skills_list(category.value if category else None, level)

    @skills_app.command("top")
    def skills_top(
        n: int = typer.Option(10, "--n", help="Number of skills to show (default: 10)"),
        category: Optional[SkillCategory] = typer.Option(None, "--category", help="Filter by category"),
    ):
        """Show top most demanded missing skills."""
        run_skills_top(n, category.value if category else None)

    @skills_app.command("clear")
    def skills_clear():
        """Clear all tracked skills."""
        run_skills_clear()
