import typer

from src.cli.apply_command import register_apply_command
from src.cli.connect_command import register_connect_command
from src.cli.report_command import register_report_command
from src.cli.misc_commands import register_misc_commands
from src.cli.skills_commands import register_skills_commands
from src.cli.answers_commands import register_answers_commands
from src.cli.provider_commands import register_provider_commands, register_key_commands


def _add_group(parent: typer.Typer, name: str, help_text: str, register_fn) -> typer.Typer:
    sub = typer.Typer(help=help_text)
    parent.add_typer(sub, name=name)
    register_fn(sub)
    return sub


def build_router(app: typer.Typer) -> None:
    register_apply_command(app)
    register_connect_command(app)
    register_report_command(app)
    register_misc_commands(app)

    _add_group(app, "skills",  "View missing skills detected during job evaluation",  register_skills_commands)
    _add_group(app, "answers", "Manage cached form answers (files/form_answers.json)", register_answers_commands)
    provider_app = _add_group(app, "provider", "Show or change LLM provider settings", register_provider_commands)
    _add_group(provider_app, "key", "Manage API keys per provider", register_key_commands)
