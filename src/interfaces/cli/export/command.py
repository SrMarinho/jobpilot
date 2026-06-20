from pathlib import Path

import typer

from src.core.use_cases.exporter import export_applied_csv, export_rejected_csv


def register_export_command(app: typer.Typer) -> None:
    @app.command()
    def export(
        what: str = typer.Argument("applied", help="applied | rejected | all"),
        out: str = typer.Option(
            None, "--out", "-o", help="Arquivo de saída (default: .local/export_*.csv)"
        ),
    ):
        """Exporta vagas (applied/rejected) para CSV (Excel/Sheets/Notion)."""
        base = Path(".local")
        if what in ("applied", "all"):
            dest = (
                Path(out)
                if (out and what == "applied")
                else base / "export_applied.csv"
            )
            n = export_applied_csv(dest)
            print(f"✅ {n} candidaturas → {dest}")
        if what in ("rejected", "all"):
            dest = (
                Path(out)
                if (out and what == "rejected")
                else base / "export_rejected.csv"
            )
            n = export_rejected_csv(dest)
            print(f"✅ {n} rejeições → {dest}")
        if what not in ("applied", "rejected", "all"):
            print("Uso: export [applied|rejected|all] [--out arquivo.csv]")
