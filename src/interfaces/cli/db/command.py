import typer

from src.core.persistence import db


def _require_url() -> bool:
    if not db.is_db_enabled():
        print("❌ DATABASE_URL não setado — app está em modo JSON local.")
        print("   Defina DATABASE_URL no .env para usar Postgres.")
        return False
    return True


def register_db_commands(app: typer.Typer) -> None:
    @app.command("check")
    def check():
        """Testa a conexão com o Postgres."""
        if not _require_url():
            raise typer.Exit(1)
        try:
            version = db.ping()
        except Exception as e:
            print(f"❌ Falha ao conectar: {e}")
            raise typer.Exit(1)
        print(f"✅ Conectado: {version}")

    @app.command("init")
    def init():
        """Cria o schema (idempotente)."""
        if not _require_url():
            raise typer.Exit(1)
        db.init_schema()
        print("✅ Schema garantido.")

    @app.command("migrate")
    def migrate():
        """Migra os .local/files/*.json atuais para o Postgres (idempotente)."""
        if not _require_url():
            raise typer.Exit(1)
        from src.core.persistence.migrate import migrate_json_to_pg

        db.init_schema()
        counts = migrate_json_to_pg()
        print("✅ Migração concluída:")
        for name, n in counts.items():
            print(f"  • {name}: {n}")

    @app.command("pull")
    def pull():
        """Puxa o Postgres de volta pros .local/files/*.json (reverso de migrate).

        Sobrescreve os arquivos locais com o conteúdo do banco.
        """
        if not _require_url():
            raise typer.Exit(1)
        from src.core.persistence.migrate import migrate_pg_to_json

        counts = migrate_pg_to_json()
        print("[OK] Pull DB->local concluido:")
        for name, n in counts.items():
            print(f"  - {name}: {n}")

    @app.command("status")
    def status():
        """Conta linhas por tabela no Postgres."""
        if not _require_url():
            raise typer.Exit(1)
        from src.core.persistence.migrate import table_counts

        for name, n in table_counts().items():
            print(f"  {name}: {n}")
