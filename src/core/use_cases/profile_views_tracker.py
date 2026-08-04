from datetime import date
from pathlib import Path

from src.config.settings import files_dir
from src.core.persistence.daily_snapshot_tracker import DailySnapshotTracker

PROFILE_VIEWS_FILE = files_dir / "profile_views.json"


class ProfileViewsTracker(DailySnapshotTracker):
    """Snapshot diário da contagem de visualizações do perfil (janela 90 dias).

    O valor é um total *rolante* de 90 dias, não cumulativo. Por isso a análise
    olha a 1ª derivada (variação/dia = ritmo) e a 2ª (variação do ritmo =
    aceleração) — responde "está subindo?" E "está acelerando?".
    """

    table = "profile_views"

    def __init__(self, path: Path = PROFILE_VIEWS_FILE):
        super().__init__(path)

    def build_snapshot(self, views: int) -> dict:
        return {"views": int(views)}

    def _daily_rates(self) -> list[tuple[date, float]]:
        """Variação por dia entre snapshots consecutivos (normaliza buracos)."""
        snaps = self.sorted_snapshots()
        rates: list[tuple[date, float]] = []
        for prev, cur in zip(snaps, snaps[1:]):
            d0, d1 = self.snapshot_date(prev), self.snapshot_date(cur)
            span = (d1 - d0).days or 1
            rates.append((d1, (cur["views"] - prev["views"]) / span))
        return rates

    def analyze(self, window: int = 7) -> dict:
        """Tendência + aceleração.

        Compara ritmo médio (visitas/dia) da janela recente vs a janela anterior.
        ``accel`` > 0 => acelerando; < 0 => desacelerando.
        """
        snaps = self.sorted_snapshots()
        out: dict = {
            "samples": len(snaps),
            "current": snaps[-1]["views"] if snaps else None,
            "first": snaps[0]["views"] if snaps else None,
            "trend": "insuficiente",
            "accel": None,
            "rate_recent": None,
            "rate_prior": None,
        }
        rates = self._daily_rates()
        if len(rates) < 2:
            return out

        vals = [r for _, r in rates]
        recent = vals[-window:]
        prior = vals[-2 * window : -window] or vals[: max(1, len(vals) - len(recent))]
        rate_recent = sum(recent) / len(recent)
        rate_prior = sum(prior) / len(prior) if prior else rate_recent
        accel = rate_recent - rate_prior

        out["rate_recent"] = round(rate_recent, 2)
        out["rate_prior"] = round(rate_prior, 2)
        out["accel"] = round(accel, 2)

        # Tendência (sinal do ritmo recente) + aceleração (sinal da 2ª derivada).
        eps = 0.05
        if rate_recent > eps:
            direction = "subindo"
        elif rate_recent < -eps:
            direction = "caindo"
        else:
            direction = "estável"
        if accel > eps:
            pace = "acelerando"
        elif accel < -eps:
            pace = "desacelerando"
        else:
            pace = "ritmo constante"
        out["trend"] = direction
        out["pace"] = pace
        return out
