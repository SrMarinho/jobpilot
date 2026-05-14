from __future__ import annotations

from typing import Callable

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header, Static

from src.automation.tasks.base_application_manager import BaseJobApplicationManager, JobItem

_STATE_STYLE = {
    "extracted":  "cyan",
    "evaluating": "bold blue",
    "approved":   "bold green",
    "rejected":   "red",
    "applying":   "bold magenta",
    "applied":    "bold green on black",
    "failed":     "bold red",
}


class JobPipelineApp(App):
    CSS = """
    DataTable {
        height: 1fr;
        border: solid $primary;
    }
    #stats {
        height: 1;
        dock: bottom;
        content-align: center middle;
        background: $surface;
        color: $text;
    }
    """

    def __init__(self, manager_factory: Callable[[Callable], BaseJobApplicationManager]):
        super().__init__()
        self._manager_factory = manager_factory
        self._rows: dict[str, str] = {}
        self._prev_state: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="jobs-table")
        yield Static(id="stats")
        yield Footer()

    def on_mount(self):
        t = self.query_one("#jobs-table", DataTable)
        t.add_columns(("#", "#"), ("Title", "Title"), ("State", "State"), ("Note", "Note"))
        t.border_title = "Jobs"
        self._update_stats()
        self.run_worker(self._run_pipeline(), name="pipeline", exclusive=True)

    async def _run_pipeline(self):
        manager = self._manager_factory(self._on_job_update)
        await manager.run()
        self.exit(0)

    def _on_job_update(self, item: JobItem):
        from dataclasses import replace
        self.call_later(self._update_ui, replace(item))

    def _update_ui(self, item: JobItem):
        key = item.job_url or str(id(item))
        tbl = self.query_one("#jobs-table", DataTable)
        style = _STATE_STYLE.get(item.state, "")
        styled_state = f"[{style}]{item.state}[/]"

        if key in self._rows:
            rk = self._rows[key]
            tbl.update_cell(rk, "#", str(item.idx))
            tbl.update_cell(rk, "Title", item.title[:60])
            tbl.update_cell(rk, "State", styled_state)
            tbl.update_cell(rk, "Note", item.note[:60])
        else:
            self._rows[key] = tbl.add_row(str(item.idx), item.title[:60], styled_state, item.note[:60])

        old_state = self._prev_state.get(key)
        if old_state:
            self._counts[old_state] = max(0, self._counts.get(old_state, 0) - 1)
        self._prev_state[key] = item.state
        self._counts[item.state] = self._counts.get(item.state, 0) + 1
        self._update_stats()

    def _update_stats(self):
        c = self._counts
        content = (
            f"[cyan]extracted:[/] {c.get('extracted', 0)}  "
            f"[blue]evaluating:[/] {c.get('evaluating', 0)}  "
            f"[green]approved:[/] {c.get('approved', 0)}  "
            f"[bold green]applied:[/] {c.get('applied', 0)}  "
            f"[red]rejected:[/] {c.get('rejected', 0)}  "
            f"[bold red]failed:[/] {c.get('failed', 0)}"
        )
        self.query_one("#stats", Static).update(content)
