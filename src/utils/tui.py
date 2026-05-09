"""Optional Rich-based TUI for the apply pipeline.

Activated via `--tui` flag. Imports rich lazily so it stays optional.
Manager calls `board.update(item)` on each state change of a JobItem.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.automation.tasks.base_application_manager import JobItem


_STATE_STYLE = {
    "pending":    "white",
    "extracted":  "cyan",
    "filtered":   "yellow",
    "evaluating": "bold blue",
    "approved":   "bold green",
    "rejected":   "red",
    "applying":   "bold magenta",
    "applied":    "bold green on black",
    "failed":     "bold red",
}


class TuiBoard:
    """Live job-pipeline status board.

    Thread-safe-ish: update() may be called from sync code; live rendering happens
    in a background refresh thread managed by rich.live.
    """
    def __init__(self):
        from rich.console import Console
        from rich.live import Live
        from rich.table import Table
        from rich.layout import Layout

        self._Console = Console
        self._Table = Table
        self._Layout = Layout
        self._console = Console()
        self._items: dict[int, "JobItem"] = {}
        self._lock = threading.Lock()
        self._live: Live | None = None

    def __enter__(self):
        from rich.live import Live
        self._live = Live(self._render(), console=self._console, refresh_per_second=4, screen=False)
        self._live.__enter__()
        return self

    def __exit__(self, *exc):
        if self._live:
            self._live.__exit__(*exc)
            self._live = None

    def update(self, item: "JobItem") -> None:
        with self._lock:
            self._items[item.idx] = item
        if self._live:
            try:
                self._live.update(self._render())
            except Exception:
                pass

    def _render(self):
        Table = self._Table
        Layout = self._Layout

        eval_tbl = Table(title="Eval", expand=True)
        eval_tbl.add_column("#", width=4)
        eval_tbl.add_column("Title", overflow="ellipsis", no_wrap=True)
        eval_tbl.add_column("State", width=12)
        eval_tbl.add_column("Note", overflow="ellipsis", no_wrap=True)

        apply_tbl = Table(title="Apply", expand=True)
        apply_tbl.add_column("#", width=4)
        apply_tbl.add_column("Title", overflow="ellipsis", no_wrap=True)
        apply_tbl.add_column("State", width=12)
        apply_tbl.add_column("Note", overflow="ellipsis", no_wrap=True)

        with self._lock:
            items = list(self._items.values())

        counts = {"applied": 0, "rejected": 0, "approved": 0, "failed": 0, "evaluating": 0}
        for it in items:
            counts[it.state] = counts.get(it.state, 0) + 1
            style = _STATE_STYLE.get(it.state, "white")
            row = (str(it.idx), it.title[:60], f"[{style}]{it.state}[/]", it.note[:60])
            target = apply_tbl if it.state in ("applying", "applied", "failed", "approved") else eval_tbl
            target.add_row(*row)

        layout = Layout()
        layout.split_column(
            Layout(name="top", ratio=8),
            Layout(name="footer", size=3),
        )
        layout["top"].split_row(Layout(eval_tbl), Layout(apply_tbl))
        footer = (
            f"[cyan]eval:[/] {counts.get('evaluating',0)}  "
            f"[green]approved:[/] {counts.get('approved',0)}  "
            f"[bold green]applied:[/] {counts.get('applied',0)}  "
            f"[red]rejected:[/] {counts.get('rejected',0)}  "
            f"[bold red]failed:[/] {counts.get('failed',0)}"
        )
        from rich.panel import Panel
        layout["footer"].update(Panel(footer, title="Stats"))
        return layout
