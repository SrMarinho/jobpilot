"""CLI: gerenciamento de competências do perfil LinkedIn.

Três modos de especificação:
  A) Arquivo de config  → set + sync
  B) Argumento CLI      → add / delete
  C) Skills tracker     → sync-from-tracker
"""

import os
from typing import List, Optional

import typer

from src.interfaces.cli.browser import run_browser_task
from src.core.use_cases.linkedin_profile_skills import LinkedInProfileSkills


def _require_profile_slug() -> str:
    slug = os.getenv("LINKEDIN_PROFILE_SLUG", "").strip()
    if not slug:
        typer.echo(
            "Error: LINKEDIN_PROFILE_SLUG not set in .env (e.g. LINKEDIN_PROFILE_SLUG=sr-marinho)",
            err=True,
        )
        raise typer.Exit(1)
    return slug


def _print_results(label: str, results: dict[str, bool]) -> None:
    if not results:
        return
    typer.echo(f"\n{label}:")
    for skill, ok in results.items():
        typer.echo(f"  {'[ok]' if ok else '[x] '} {skill}")


def _print_add_outcome(out: dict) -> None:
    """Imprime o resultado de add_skills: adicionadas, puladas (já existem) e limite."""
    skipped = out.get("skipped", [])
    if skipped:
        typer.echo("\nJa existiam (puladas):")
        for skill in skipped:
            typer.echo(f"  - ja existe (skip): {skill}")
    _print_results("Added", out.get("added", {}))
    if out.get("limit_reached"):
        typer.echo(
            "\n[!] Limite de competencias do LinkedIn atingido - "
            "as restantes nao foram adicionadas."
        )
    if not skipped and not out.get("added"):
        typer.echo("Nada a fazer.")


def register_profile_skills_commands(app: typer.Typer) -> None:
    # ── B: args diretos ──────────────────────────────────────────────

    @app.command("list")
    def cmd_list(ctx: typer.Context):
        """Scrape e lista todas as competências atuais do perfil LinkedIn."""
        slug = _require_profile_slug()
        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            result["skills"] = await mgr.list_skills()

        run_browser_task(ctx, "skills-list", _work)

        skills = result.get("skills", [])
        if not skills:
            typer.echo("No skills found on profile (or page did not load).")
            return
        typer.echo(f"Profile skills ({len(skills)}):")
        for s in skills:
            typer.echo(f"  - {s}")

    @app.command("add")
    def cmd_add(
        ctx: typer.Context,
        skills: List[str] = typer.Argument(..., help="Competências a adicionar"),
        force: bool = typer.Option(
            False,
            "--force",
            help="Readiciona mesmo se já existir (default: pula existentes)",
        ),
    ):
        """Adiciona competências ao perfil LinkedIn. Idempotente: pula as que já existem."""
        slug = _require_profile_slug()
        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            result["out"] = await mgr.add_skills(list(skills), force=force)

        run_browser_task(ctx, "skills-add", _work)
        _print_add_outcome(result.get("out", {}))

    @app.command("delete")
    def cmd_delete(
        ctx: typer.Context,
        skills: List[str] = typer.Argument(..., help="Competências a deletar"),
    ):
        """Deleta uma ou mais competências do perfil LinkedIn."""
        slug = _require_profile_slug()
        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            result["deleted"] = await mgr.delete_skills(list(skills))

        run_browser_task(ctx, "skills-delete", _work)
        _print_results("Deleted", result.get("deleted", {}))

    # ── A: config file ───────────────────────────────────────────────

    @app.command("set")
    def cmd_set(
        skills: List[str] = typer.Argument(..., help="Lista desejada de competências"),
    ):
        """Define a lista local desejada de competências (sem abrir browser)."""
        store = LinkedInProfileSkills()
        store.save(list(skills))
        typer.echo(f"Saved {len(skills)} desired skills:")
        for s in skills:
            typer.echo(f"  - {s}")

    @app.command("show-desired")
    def cmd_show_desired():
        """Mostra a lista local desejada de competências."""
        store = LinkedInProfileSkills()
        skills = store.load()
        if not skills:
            typer.echo(
                "No desired skills configured. Use `profile skills set <skills...>`."
            )
            return
        typer.echo(f"Desired skills ({len(skills)}):")
        for s in skills:
            typer.echo(f"  - {s}")

    @app.command("sync")
    def cmd_sync(ctx: typer.Context):
        """Sincroniza perfil LinkedIn com a lista desejada (set + sync).

        Deleta competências não desejadas, adiciona as que faltam.
        """
        slug = _require_profile_slug()
        store = LinkedInProfileSkills()
        desired = store.load()

        if not desired:
            typer.echo(
                "No desired skills configured. Use `profile skills set <skills...>` first.",
                err=True,
            )
            raise typer.Exit(1)

        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            result["sync"] = await mgr.sync_skills(desired)

        run_browser_task(ctx, "skills-sync", _work)

        sync = result.get("sync", {})
        typer.echo(f"Profile had {len(sync.get('current', []))} skills.")
        _print_results("Deleted", sync.get("deleted", {}))
        _print_results("Added", sync.get("added", {}))
        if not sync.get("deleted") and not sync.get("added"):
            typer.echo("Profile already matches desired skills. Nothing to do.")

    # ── C: skills tracker ────────────────────────────────────────────

    @app.command("sync-from-tracker")
    def cmd_sync_from_tracker(
        ctx: typer.Context,
        top_n: int = typer.Option(20, "--top", "-n", help="Top N skills do tracker"),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Só mostra o que seria feito"
        ),
    ):
        """Sincroniza perfil com as top-N skills mais demandadas nos jobs avaliados.

        Fonte: skills_tracker (rastreado automaticamente durante apply/evaluate).
        """
        from_tracker = LinkedInProfileSkills.from_skills_tracker(top_n)

        if not from_tracker:
            typer.echo("No skills in tracker yet. Run apply/evaluate first.")
            raise typer.Exit(1)

        typer.echo(f"Top {len(from_tracker)} skills from tracker:")
        for s in from_tracker:
            typer.echo(f"  - {s}")

        if dry_run:
            typer.echo("\n[dry-run] Would sync these to LinkedIn profile.")
            return

        slug = _require_profile_slug()
        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            result["sync"] = await mgr.sync_skills(from_tracker)

        run_browser_task(ctx, "skills-sync-tracker", _work)

        sync = result.get("sync", {})
        typer.echo(f"\nProfile had {len(sync.get('current', []))} skills.")
        _print_results("Deleted", sync.get("deleted", {}))
        _print_results("Added", sync.get("added", {}))
        if not sync.get("deleted") and not sync.get("added"):
            typer.echo("Profile already matches tracker skills. Nothing to do.")

    # ── D: seed file versionado ──────────────────────────────────────

    @app.command("seed")
    def cmd_seed(
        ctx: typer.Context,
        from_file: Optional[str] = typer.Option(
            None,
            "--from-file",
            help="Seed alternativo (default: data/linkedin_skills_seed.txt)",
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Só mostra a lista (sem browser)"
        ),
        add_only: bool = typer.Option(
            False, "--add-only", help="Só adiciona faltantes (não deleta nada)"
        ),
        limit: int = typer.Option(
            0,
            "--limit",
            help="Trunca nas N primeiras (0 = sem cap, LinkedIn dita o teto)",
        ),
    ):
        """Sincroniza o perfil com o seed versionado de competências.

        Default = sync (perfil = seed: deleta fora da lista + adiciona faltantes).
        --add-only nunca deleta. Idempotente: rerun não duplica.
        """
        from pathlib import Path

        path = Path(from_file) if from_file else None
        desired = LinkedInProfileSkills.from_seed_file(path)
        if not desired:
            typer.echo("Seed vazio ou não encontrado.")
            raise typer.Exit(1)

        if limit > 0:
            desired = desired[:limit]

        typer.echo(f"Seed: {len(desired)} competências (normalizadas, dedupe).")
        for s in desired:
            typer.echo(f"  - {s}")

        if dry_run:
            mode = (
                "add-only (sem deletar)" if add_only else "sync (deleta fora da lista)"
            )
            typer.echo(f"\n[dry-run] Modo: {mode}. Nada foi alterado.")
            return

        slug = _require_profile_slug()
        result: dict = {}

        async def _work(page):
            from src.automation.tasks.linkedin_skills_manager import (
                LinkedInSkillsManager,
            )

            mgr = LinkedInSkillsManager(page, slug)
            if add_only:
                result["out"] = await mgr.add_missing(desired)
            else:
                result["out"] = await mgr.sync_skills(desired)

        run_browser_task(ctx, "skills-seed", _work)

        out = result.get("out", {})
        if "current" in out:  # sync
            typer.echo(f"\nProfile had {len(out.get('current', []))} skills.")
            _print_results("Deleted", out.get("deleted", {}))
        _print_add_outcome(out)
