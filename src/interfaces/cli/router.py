import typer

from src.interfaces.cli.apply.command import register_apply_command
from src.interfaces.cli.connect.command import register_connect_command
from src.interfaces.cli.engage.command import register_engage_command
from src.interfaces.cli.autopost.command import register_autopost_command
from src.interfaces.cli.report.command import register_report_command
from src.interfaces.cli.export.command import register_export_command
from src.interfaces.cli.searches.command import register_searches_commands
from src.interfaces.cli.goals.command import register_goals_commands
from src.interfaces.cli.dashboard.command import register_dashboard_command
from src.interfaces.cli.followup.command import register_followup_command
from src.interfaces.cli.misc.command import register_misc_commands
from src.interfaces.cli.skills.command import register_skills_commands
from src.interfaces.cli.answers.command import register_answers_commands
from src.interfaces.cli.provider.command import (
    register_provider_commands,
    register_key_commands,
)


def _add_group(
    parent: typer.Typer, name: str, help_text: str, register_fn
) -> typer.Typer:
    sub = typer.Typer(help=help_text)
    parent.add_typer(sub, name=name)
    register_fn(sub)
    return sub


def register(app: typer.Typer) -> None:
    @app.callback()
    def _callback(
        ctx: typer.Context,
        headless: bool = typer.Option(
            False,
            "--headless",
            help="Force headless Chrome (overrides HEADLESS env var)",
        ),
    ):
        ctx.ensure_object(dict)
        ctx.obj["headless"] = headless

    register_apply_command(app)
    register_connect_command(app)
    register_engage_command(app)
    register_autopost_command(app)
    register_followup_command(app)
    register_report_command(app)
    register_export_command(app)
    register_dashboard_command(app)
    register_misc_commands(app)

    _add_group(
        app,
        "searches",
        "Manage rotating saved-searches (connect/apply)",
        register_searches_commands,
    )
    _add_group(
        app,
        "goals",
        "Weekly goals (applications/connections/posts/comments)",
        register_goals_commands,
    )
    _add_group(
        app,
        "skills",
        "View missing skills detected during job evaluation",
        register_skills_commands,
    )
    _add_group(
        app,
        "answers",
        "Manage cached form answers (files/form_answers.json)",
        register_answers_commands,
    )
    provider_app = _add_group(
        app,
        "provider",
        "Show or change LLM provider settings",
        register_provider_commands,
    )
    _add_group(
        provider_app, "key", "Manage API keys per provider", register_key_commands
    )
