import typer

from src.cli.answers_logic import (
    run_answers_list, run_answers_show, run_answers_set,
    run_answers_fill, run_answers_clear,
)


def register_answers_commands(answers_app: typer.Typer) -> None:
    @answers_app.command("list")
    def answers_list():
        """Show questions with missing answers (numbered)."""
        run_answers_list()

    @answers_app.command("show")
    def answers_show():
        """Show all cached answers (numbered)."""
        run_answers_show()

    @answers_app.command("fill")
    def answers_fill():
        """Interactively answer all missing questions one by one."""
        run_answers_fill()

    @answers_app.command("set")
    def answers_set(
        number: int = typer.Argument(..., help="Question number shown in 'answers list' or 'answers show'"),
        answer: str = typer.Argument(..., help="Answer to save"),
    ):
        """Set an answer by question number (from list/show)."""
        run_answers_set(number, answer)

    @answers_app.command("clear")
    def answers_clear():
        """Remove all cached answers."""
        run_answers_clear()
