from typing import Optional

import typer

from src.config.settings import logger
from src.core.use_cases import manual_apply
from src.core.use_cases.resume_loader import load_resume_text
from src.interfaces.cli.apply_external.logic import run_external_apply
from src.interfaces.cli.browser import run_browser_simple
from src.interfaces.cli.persistence import _find_resume
from src.utils.async_utils import run_async
from src.utils.logger import set_run_context


def register_apply_external_command(app: typer.Typer) -> None:
    """Registra ``jobs apply-external`` sob o grupo informado."""

    @app.command("apply-external")
    def apply_external(
        ctx: typer.Context,
        job_url: Optional[str] = typer.Argument(
            None,
            help="URL da vaga no LinkedIn/Indeed, ou o link direto do formulário",
        ),
        from_manual: int = typer.Option(
            0,
            "--from-manual",
            min=0,
            help="Processa as N vagas mais recentes da fila de candidatura manual",
        ),
        resume: Optional[str] = typer.Option(
            None, "--resume", help="Currículo a anexar (default: o de sempre)"
        ),
        dry_run: bool = typer.Option(
            False,
            "--dry-run",
            help="Só extrai e imprime o formulário — não preenche, não envia",
        ),
        no_submit: bool = typer.Option(
            False, "--no-submit", help="Preenche tudo, mas não clica em enviar"
        ),
        list_queue: bool = typer.Option(
            False, "--list", help="Lista a fila de candidaturas manuais e sai"
        ),
    ):
        """Candidatura em formulário externo, com o LLM lendo a página.

        Comando manual: o LLM lê todos os campos do formulário do ATS, responde
        com o banco de Q&A e o currículo, preenche e envia. Não entra no
        agendamento — envio em site de terceiro é decisão de quem está olhando.
        """
        if list_queue:
            fila = manual_apply.pending()
            print(f"{len(fila)} vaga(s) na fila de candidatura manual:\n")
            for url, entry in fila:
                marca = "✓" if entry.get("external_url") else " "
                print(
                    f" {marca} {entry.get('title', '?')} — {entry.get('company', '?')}"
                )
                print(f"     {url}")
            print("\n(✓ = link do formulário externo já resolvido)")
            return

        targets: list[str] = []
        if job_url:
            targets.append(job_url)
        if from_manual:
            targets.extend(url for url, _ in manual_apply.pending(from_manual))
        if not targets:
            raise typer.BadParameter("passe a URL da vaga ou --from-manual N")

        resume_file = _find_resume(resume or "")
        resume_text = load_resume_text(resume_file)

        set_run_context("apply-external")

        async def _work(page):
            for i, url in enumerate(targets, 1):
                logger.info(f"[{i}/{len(targets)}] {url}")
                try:
                    ok = await run_external_apply(
                        page,
                        url,
                        resume_text=resume_text,
                        resume_file=resume_file,
                        dry_run=dry_run,
                        no_submit=no_submit,
                    )
                except Exception as e:
                    # Um ATS quebrado não pode derrubar a fila inteira.
                    logger.error(f"Falhou em {url}: {e}")
                    continue
                logger.info(
                    f"[{i}/{len(targets)}] {'enviada' if ok else 'não enviada'}"
                )

        # run_browser_simple, não run_browser: comando interativo, o browser
        # fica visível e espera antes de fechar pra você conferir o resultado.
        run_async(run_browser_simple(_work, headless=False, post_wait_ms=5000))
