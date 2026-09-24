"""Índice de presença: substituto próprio do SSI.

O LinkedIn descontinuou o Social Selling Index ("Seu acesso ao SSI foi
descontinuado"), e a série que o relatório acompanhava parou. Este índice
recria os mesmos quatro pilares (0-25 cada, total 0-100) com o que o JobPilot
já registra, sem raspar página nenhuma.

Cada métrica é comparada com a SUA média das semanas anteriores, não com uma
régua externa: 12,5/25 num pilar = semana na média, 25/25 = o dobro ou mais.
Não é comparável com o SSI antigo; serve para a mesma coisa que ele servia na
prática — dizer se a presença está subindo ou caindo.

Funções puras: recebem números, devolvem números. Quem coleta é o
``MetricsCalculator`` do relatório.
"""

from collections.abc import Mapping

#: pilar -> [(métrica, peso)]. Pesos de cada pilar somam 1.
PILLARS: dict[str, list[tuple[str, float]]] = {
    # Quanto o perfil é visto e quanto você publica.
    "brand": [("views", 0.6), ("posts", 0.4)],
    # Quanto você é encontrado e quanto prospecta.
    "find_people": [("appearances", 0.6), ("invites", 0.4)],
    # Quanto você participa da conversa dos outros.
    "engage_insights": [("comments", 0.6), ("shares", 0.2), ("likes", 0.2)],
    # Contato direto e variedade de pessoas com quem interagiu.
    "relationships": [("dms", 0.6), ("people", 0.4)],
}

METRICS: tuple[str, ...] = tuple(m for parts in PILLARS.values() for m, _ in parts)

PILLAR_MAX = 25.0
# Teto da razão semana/média: o dobro da média já vale nota cheia. Sem teto,
# uma semana fora da curva (um post que viralizou) esconderia os outros pilares.
_RATIO_CAP = 2.0


def metric_score(value: float, baseline: float | None) -> float:
    """0..1 para uma métrica. 0,5 = igual à média."""
    if value <= 0:
        return 0.0
    if not baseline or baseline <= 0:
        # Sem histórico (ou histórico zerado) não há régua: ter feito algo vale
        # "na média", e não nota cheia, para não inflar as primeiras semanas.
        return 0.5
    return min(value / baseline, _RATIO_CAP) / _RATIO_CAP


def baseline(history: list[Mapping[str, float]]) -> dict[str, float]:
    """Média de cada métrica nas semanas anteriores.

    Métrica ausente numa semana (snapshot de views não capturado, por exemplo)
    fica fora da média daquela métrica em vez de contar como zero.
    """
    out: dict[str, float] = {}
    for m in METRICS:
        seen = [float(h[m]) for h in history if h.get(m) is not None]
        if seen:
            out[m] = sum(seen) / len(seen)
    return out


def _component(metric: str, values: Mapping, base: Mapping) -> float:
    value = values.get(metric)
    if value is None:
        # Não medido nesta semana: neutro se há histórico, zero se nunca houve.
        return 0.5 if base.get(metric) else 0.0
    return metric_score(float(value), base.get(metric))


def score(values: Mapping[str, float | None], base: Mapping[str, float]) -> dict:
    """Índice da semana: os quatro pilares (0-25) + ``total`` (0-100)."""
    out: dict = {}
    for pillar, parts in PILLARS.items():
        s = sum(w * _component(m, values, base) for m, w in parts)
        out[pillar] = round(s * PILLAR_MAX, 1)
    out["total"] = round(sum(out[p] for p in PILLARS), 1)
    return out
