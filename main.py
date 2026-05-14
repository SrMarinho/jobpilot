from dotenv import load_dotenv
import typer

from src.cli.router import build_router

app = typer.Typer(help="JobPilot — Automated job application bot")


@app.callback()
def _callback(
    ctx: typer.Context,
    headless: bool = typer.Option(False, "--headless", help="Force headless Chrome (overrides HEADLESS env var)"),
):
    ctx.ensure_object(dict)
    ctx.obj["headless"] = headless


build_router(app)


def main():
    app()


if __name__ == "__main__":
    load_dotenv()
    main()
