import typer

from src.core.use_cases.saved_searches import SavedSearches


def register_searches_commands(app: typer.Typer) -> None:
    @app.command("list")
    def list_searches(
        task: str = typer.Option(None, "--task", help="Filtra por tarefa"),
    ):
        """Lista as buscas salvas (rodízio)."""
        searches = SavedSearches().list(task)
        if not searches:
            print("Nenhuma busca salva. Use 'searches add'.")
            return
        for i, s in enumerate(SavedSearches().list()):
            if task and s.get("task") != task:
                continue
            print(f"[{i}] ({s.get('task')}) {s.get('label')} → {s.get('url')}")

    @app.command("add")
    def add_search(
        label: str = typer.Argument(..., help="Rótulo curto"),
        url: str = typer.Argument(..., help="URL completa da busca"),
        task: str = typer.Option("connect", "--task", help="connect|apply"),
    ):
        """Adiciona uma busca à fila de rodízio."""
        SavedSearches().add(label, url, task)
        print(f"Adicionada: {label} ({task})")

    @app.command("remove")
    def remove_search(index: int = typer.Argument(..., help="Índice (ver 'list')")):
        """Remove uma busca pelo índice."""
        removed = SavedSearches().remove(index)
        if removed:
            print(f"Removida: {removed.get('label')}")
        else:
            print("Índice inválido.")

    @app.command("next")
    def next_search(
        task: str = typer.Option("connect", "--task", help="connect|apply"),
    ):
        """Mostra a próxima busca do rodízio (avança o cursor)."""
        nxt = SavedSearches().next(task)
        if nxt:
            print(f"Próxima ({task}): {nxt.get('label')} → {nxt.get('url')}")
        else:
            print(f"Nenhuma busca salva para '{task}'.")
