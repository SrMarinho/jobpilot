from __future__ import annotations

from typing import Callable

from textual.app import App, ComposeResult
from textual.containers import Horizontal
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
    Horizontal {
        height: 1fr;
    }
    DataTable {
        height: 100%;
        border: solid $primary;
    }
    DataTable#active-table {
        border: solid cyan;
    }
    DataTable#approved-table {
        border: solid green;
    }
    DataTable#rejected-table {
        border: solid red;
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
        self._rows: dict[str, tuple[str, str]] = {}
        self._prev_state: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            yield DataTable(id="active-table")
            yield DataTable(id="approved-table")
            yield DataTable(id="rejected-table")
        yield Static(id="stats")
        yield Footer()

    def on_mount(self):
        for tid, title in [("active-table", "Active"), ("approved-table", "Approved"), ("rejected-table", "Rejected")]:
            t = self.query_one(f"#{tid}", DataTable)
            t.add_columns(("#", "#"), ("Title", "Title"), ("State", "State"), ("Note", "Note"))
            t.border_title = title
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
        new_tid = self._table_id(item.state)
        tbl = self.query_one(f"#{new_tid}", DataTable)
        style = _STATE_STYLE.get(item.state, "")
        styled_state = f"[{style}]{item.state}[/]"
        row_data = (str(item.idx), item.title[:50], styled_state, item.note[:50])

        if key in self._rows:
            old_rk, old_tid = self._rows[key]
            if old_tid != new_tid:
                try:
                    self.query_one(f"#{old_tid}", DataTable).remove_row(old_rk)
                except Exception:
                    pass
                self._rows[key] = (tbl.add_row(*row_data), new_tid)
            else:
                tbl.update_cell(old_rk, "#", str(item.idx))
                tbl.update_cell(old_rk, "Title", item.title[:50])
                tbl.update_cell(old_rk, "State", styled_state)
                tbl.update_cell(old_rk, "Note", item.note[:50])
        else:
            self._rows[key] = (tbl.add_row(*row_data), new_tid)

        old_state = self._prev_state.get(key)
        if old_state:
            self._counts[old_state] = max(0, self._counts.get(old_state, 0) - 1)
        self._prev_state[key] = item.state
        self._counts[item.state] = self._counts.get(item.state, 0) + 1
        self._update_stats()

    @staticmethod
    def _table_id(state: str) -> str:
        if state in ("extracted", "evaluating"):
            return "active-table"
        if state in ("approved", "applying", "applied"):
            return "approved-table"
        return "rejected-table"  # rejected, failed

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
        stats = self.query_one("#stats", Static)
        stats.update(content)
