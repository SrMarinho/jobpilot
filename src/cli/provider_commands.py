from typing import Optional

import typer

from src.cli.provider_logic import (
    run_provider_show, run_provider_set,
    run_provider_key_set, run_provider_key_show,
)


def register_provider_commands(provider_app: typer.Typer) -> None:
    from src.cli.enums import ProviderTarget, LLMBackend

    @provider_app.command("show")
    def provider_show():
        """Show current provider configuration."""
        run_provider_show()

    @provider_app.command("set")
    def provider_set(
        target: ProviderTarget = typer.Argument(..., help="Which provider to change: 'llm' (form Q&A) or 'eval' (job evaluation)"),
        backend: LLMBackend = typer.Argument(..., help="Backend to use: claude or langchain"),
        model: Optional[str] = typer.Option(None, "--model", help="Model name (e.g. claude-haiku-4-5-20251001 or llama3.1:8b)"),
        lc_backend: Optional[str] = typer.Option(None, "--backend", help="LangChain backend: ollama (default) or deepseek"),
    ):
        """Set a provider (claude or langchain)."""
        run_provider_set(target.value, backend.value, model, lc_backend)


def register_key_commands(key_app: typer.Typer) -> None:
    @key_app.command("set")
    def provider_key_set(
        provider: str = typer.Argument(..., help="Provider name: anthropic, deepseek"),
        value: str = typer.Argument(..., help="API key value"),
    ):
        """Save an API key for a provider in .env."""
        try:
            run_provider_key_set(provider.lower(), value)
        except ValueError as e:
            print(str(e))
            raise typer.Exit(code=1)

    @key_app.command("show")
    def provider_key_show():
        """Show stored API keys (masked)."""
        run_provider_key_show()
