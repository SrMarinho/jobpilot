import typer

from src.interfaces.cli.apply.command import register_apply_command
from src.interfaces.cli.connect.command import register_connect_command
from src.interfaces.cli.engage.command import register_engage_command
from src.interfaces.cli.autopost.command import register_autopost_command
from src.interfaces.cli.report.command import register_report_command
from src.interfaces.cli.export.command import register_export_command
from src.interfaces.cli.searches.command import register_searches_commands
from src.interfaces.cli.goals.command import register_goals_commands
from src.interfaces.cli.canary.command import register_canary_command
from src.interfaces.cli.queue.command import register_queue_command
from src.interfaces.cli.triage.command import register_triage_command
from src.interfaces.cli.limits.command import register_limits_command
from src.interfaces.cli.profile.capture.command import register_profile_capture_command
from src.interfaces.cli.profile.skills.command import register_profile_skills_commands
from src.interfaces.cli.profile.views.command import register_profile_views_commands
from src.interfaces.cli.profile.ssi.command import register_profile_ssi_commands
from src.interfaces.cli.profile.appearances.command import (
    register_profile_appearances_commands,
)
from src.interfaces.cli.db.command import register_db_commands
from src.interfaces.cli.dashboard.command import register_dashboard_command
from src.interfaces.cli.followup.command import register_followup_command
from src.interfaces.cli.hired.command import register_hired_command
from src.interfaces.cli.misc.command import (
    register_misc_commands,
    register_test_apply_command,
)
from src.interfaces.cli.telegram_topics.command import register_telegram_topics_commands
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

    # ── Top-level utilities ───────────────────────────────────────────
    register_misc_commands(app)  # login, logout, bot

    # ── jobs: vagas e candidaturas ────────────────────────────────────
    jobs_app = typer.Typer(help="Job search & applications")
    app.add_typer(jobs_app, name="jobs")
    register_apply_command(jobs_app)
    register_hired_command(jobs_app)
    register_queue_command(jobs_app)
    register_triage_command(jobs_app)
    register_export_command(jobs_app)
    register_test_apply_command(jobs_app)
    _add_group(
        jobs_app,
        "searches",
        "Rotating saved-searches (connect/apply)",
        register_searches_commands,
    )
    _add_group(
        jobs_app,
        "skills",
        "Missing skills detected during job evaluation",
        register_skills_commands,
    )
    _add_group(
        jobs_app,
        "answers",
        "Cached form answers (form_answers.json)",
        register_answers_commands,
    )

    # ── network: networking LinkedIn ──────────────────────────────────
    network_app = typer.Typer(help="LinkedIn networking (connections & follow-up DMs)")
    app.add_typer(network_app, name="network")
    register_connect_command(network_app)
    register_followup_command(network_app)

    # ── content: conteúdo LinkedIn ────────────────────────────────────
    content_app = typer.Typer(help="LinkedIn content (feed engagement & posts)")
    app.add_typer(content_app, name="content")
    register_engage_command(content_app)
    register_autopost_command(content_app)

    # ── profile: perfil LinkedIn ──────────────────────────────────────
    profile_app = typer.Typer(help="LinkedIn profile management")
    app.add_typer(profile_app, name="profile")
    register_profile_capture_command(profile_app)
    _add_group(
        profile_app,
        "skills",
        "Add/delete/sync LinkedIn profile skills",
        register_profile_skills_commands,
    )
    _add_group(
        profile_app,
        "views",
        "Track & analyze 90-day profile views",
        register_profile_views_commands,
    )
    _add_group(
        profile_app,
        "ssi",
        "Social Selling Index: show score + history",
        register_profile_ssi_commands,
    )
    _add_group(
        profile_app,
        "appearances",
        "Search appearances: count + trend",
        register_profile_appearances_commands,
    )

    # ── insights: relatórios e dashboard ─────────────────────────────
    insights_app = typer.Typer(help="Reports & analytics dashboard")
    app.add_typer(insights_app, name="insights")
    register_report_command(insights_app)
    register_dashboard_command(insights_app)

    # ── config: configuração do sistema ──────────────────────────────
    config_app = typer.Typer(help="System configuration (LLM, DB, Telegram, goals)")
    app.add_typer(config_app, name="config")
    register_limits_command(config_app)
    register_canary_command(config_app)
    _add_group(
        config_app,
        "telegram-topics",
        "Telegram topic sessions: setup/list/reset",
        register_telegram_topics_commands,
    )
    _add_group(
        config_app,
        "goals",
        "Weekly goals (applications/connections/posts/comments)",
        register_goals_commands,
    )
    _add_group(
        config_app,
        "db",
        "Postgres backend: check/init/migrate/status",
        register_db_commands,
    )
    provider_app = _add_group(
        config_app, "provider", "LLM provider settings", register_provider_commands
    )
    _add_group(
        provider_app, "key", "Manage API keys per provider", register_key_commands
    )
