import sys

import typer
from dotenv import load_dotenv

from src.interfaces.cli.router import register

app = typer.Typer(help="JobPilot — Automated job application bot")


def _force_utf8_stdio() -> None:
    # Console Windows usa cp1252 por padrão e quebra ao imprimir conteúdo
    # unicode (posts com ≠, em-dash, acentos em pipe). Força UTF-8 no stdio.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


if __name__ == "__main__":
    _force_utf8_stdio()
    load_dotenv()
    register(app)
    app()
