"""Dashboard TUI ao vivo (textual).

View read-only do estado do JobPilot: candidaturas, conexões, engagement,
autopost, SSI e progresso de metas — sem abrir os JSONs na mão. Atualiza
sozinha a cada 30s; tecla 'r' força refresh, 'q' sai.
"""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Static, Header, Footer

from src.interfaces.tui.stats import gather_stats


def _bar(actual: int, target: int, width: int = 16) -> str:
    if target <= 0:
        return "—"
    filled = min(width, round(actual / target * width))
    pct = round(actual / target * 100)
    return f"[{'█' * filled}{'░' * (width - filled)}] {actual}/{target} ({pct}%)"


class _Panel(Static):
    """A titled panel with multi-line body text."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title
        self.body = ""

    def render(self) -> str:
        return f"[b]{self._title}[/b]\n{self.body}"


class DashboardApp(App):
    CSS = """
    Screen { background: $surface; }
    _Panel {
        border: round $primary;
        padding: 1 2;
        margin: 1;
        width: 1fr;
        height: auto;
    }
    """
    BINDINGS = [
        ("r", "refresh", "Atualizar"),
        ("q", "quit", "Sair"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll():
            with Horizontal():
                self.p_apps = _Panel("📋 Candidaturas")
                self.p_engage = _Panel("🤝 Engagement")
                yield self.p_apps
                yield self.p_engage
            with Horizontal():
                self.p_autopost = _Panel("📝 Autopost")
                self.p_ssi = _Panel("📈 SSI")
                yield self.p_autopost
                yield self.p_ssi
            self.p_goals = _Panel("🎯 Metas (semana)")
            yield self.p_goals
        yield Footer()

    def on_mount(self) -> None:
        self.title = "JobPilot Dashboard"
        self.action_refresh()
        self.set_interval(30, self.action_refresh)

    def action_refresh(self) -> None:
        try:
            s = gather_stats()
        except Exception as e:  # pragma: no cover - defensive
            self.p_apps.body = f"erro ao carregar: {e}"
            self.p_apps.refresh()
            return
        self.sub_title = f"semana {s['week']}"

        self.p_apps.body = (
            f"Hoje:        {s['apps_today']}\n"
            f"Semana:      {s['apps_week']} aplic / {s['rej_week']} rej\n"
            f"Conexões sem: {s['connections_week']}\n"
            f"Total geral: {s['applied_total']} aplic\n"
            f"Q&A pendente: {s['qa_pending']}"
        )
        eng = s["engagement"]
        self.p_engage.body = (
            f"❤️ Likes:    {eng.get('likes', 0)}\n"
            f"💬 Comments: {eng.get('comments', 0)}\n"
            f"🔁 Shares:   {eng.get('shares', 0)}"
        )
        ap = s["autopost"]
        self.p_autopost.body = (
            f"🚀 Publicados: {ap.get('published', 0)}\n"
            f"🧪 Gerados:    {ap.get('generated', 0)}\n"
            f"✅ {ap.get('approved', 0)}  ❌ {ap.get('rejected', 0)}  "
            f"⏰ {ap.get('expired', 0)}"
        )
        ssi = s["ssi"]
        if ssi:
            self.p_ssi.body = (
                f"Total: {ssi.get('total', '?')}/100\n"
                f"🏷️ {ssi.get('brand', '?')}  🔍 {ssi.get('find_people', '?')}\n"
                f"💡 {ssi.get('engage_insights', '?')}  "
                f"🤝 {ssi.get('relationships', '?')}"
            )
        else:
            self.p_ssi.body = "sem captura esta semana"
        labels = {
            "applications": "Candidaturas",
            "connections": "Conexões",
            "posts": "Posts",
            "comments": "Comentários",
        }
        self.p_goals.body = "\n".join(
            f"{labels[k]:13} {_bar(a, t)}" for k, (a, t) in s["goals"].items()
        )
        for p in (
            self.p_apps,
            self.p_engage,
            self.p_autopost,
            self.p_ssi,
            self.p_goals,
        ):
            p.refresh()


def run_dashboard() -> None:
    DashboardApp().run()
