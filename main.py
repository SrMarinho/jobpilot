import typer
from dotenv import load_dotenv

from src.interfaces.cli.router import register

app = typer.Typer(help="JobPilot — Automated job application bot")

if __name__ == "__main__":
    load_dotenv()
    register(app)
    app()
