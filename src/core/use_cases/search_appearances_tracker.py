from pathlib import Path

from src.config.settings import files_dir
from src.core.persistence.daily_snapshot_tracker import DailySnapshotTracker

SEARCH_APPEARANCES_FILE = files_dir / "search_appearances.json"


class SearchAppearancesTracker(DailySnapshotTracker):
    """Snapshot diário de "aparições em pesquisas" (janela rolante ~1 semana).

    Guarda histórico (1 snapshot/dia) p/ analisar tendência: o valor é rolante,
    então comparamos o último com o anterior pra dizer se subiu/caiu.
    """

    table = "search_appearances"

    def __init__(self, path: Path = SEARCH_APPEARANCES_FILE):
        super().__init__(path)

    def build_snapshot(self, count: int) -> dict:
        return {"count": int(count)}

    def analyze(self) -> dict:
        """Valor atual, anterior e tendência (sobe/cai/estável)."""
        snaps = self.sorted_snapshots()
        out: dict = {
            "samples": len(snaps),
            "current": snaps[-1]["count"] if snaps else None,
            "previous": snaps[-2]["count"] if len(snaps) >= 2 else None,
            "trend": "insuficiente",
            "delta": None,
        }
        if len(snaps) >= 2:
            delta = snaps[-1]["count"] - snaps[-2]["count"]
            out["delta"] = delta
            out["trend"] = (
                "subindo" if delta > 0 else "caindo" if delta < 0 else "estável"
            )
        return out
