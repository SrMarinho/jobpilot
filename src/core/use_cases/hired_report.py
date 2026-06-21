"""Aproveitamento dos dados de contratados recentes (feature `hired`).

Três saídas, na ordem de valor:
  1. **Gap** — skills em alta entre contratados que faltam no teu currículo
     (com categoria/estimativa de aprendizado, reusando `skills_tracker`).
  2. **Tendência** — skills subindo/caindo mês a mês (via `tracker.trend`).
  3. **Texto p/ Telegram** — junta agregado + gap + tendência num relatório.

Lógica de comparação é pura/testável; o enriquecimento (categoria/estimativa)
é async pois chama o LLM.
"""

import asyncio

from src.core.use_cases.skills_tracker import _assess_skill_async, _canonical_skill


def split_have_missing(
    aggregate: list[tuple[str, int]], resume_text: str
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Divide o ranking de skills em ``(tem, falta)`` comparando com o currículo.

    Uma skill conta como "tem" se seu nome canônico aparece no texto do
    currículo (case-insensitive). ``aggregate`` é ``[(skill, count), ...]``.
    """
    resume_lower = (resume_text or "").lower()
    have: list[tuple[str, int]] = []
    missing: list[tuple[str, int]] = []
    for skill, count in aggregate:
        canonical = _canonical_skill(skill)
        if canonical and canonical in resume_lower:
            have.append((skill, count))
        else:
            missing.append((skill, count))
    return have, missing


async def enrich_missing(
    missing: list[tuple[str, int]],
) -> list[dict]:
    """Anexa categoria/estimativa de aprendizado a cada skill faltante (LLM).

    Retorna ``[{skill, count, category, level, estimate}, ...]`` ordenado por
    contagem desc (mais demandadas primeiro).
    """
    if not missing:
        return []
    assessments = await asyncio.gather(
        *[_assess_skill_async(skill) for skill, _ in missing]
    )
    rows = [
        {"skill": skill, "count": count, **assessment}
        for (skill, count), assessment in zip(missing, assessments)
    ]
    rows.sort(key=lambda row: row["count"], reverse=True)
    return rows


def format_aggregate(
    aggregate: list[tuple[str, int]], role: str, days: int, limit: int = 25
) -> str:
    lines = [f"<b>Skills mais frequentes — contratados '{role}' (<={days}d)</b>"]
    if not aggregate:
        lines.append("(nada agregado ainda — rode sem --dry-run)")
        return "\n".join(lines)
    for skill, count in aggregate[:limit]:
        lines.append(f"{count:>3}x  {skill}")
    return "\n".join(lines)


def format_gap(
    have: list[tuple[str, int]], missing_enriched: list[dict], limit: int = 15
) -> str:
    lines = ["<b>Gap vs teu currículo</b>"]
    if missing_enriched:
        lines.append("Em alta que FALTAM (priorizar):")
        for row in missing_enriched[:limit]:
            lines.append(
                f"  {row['count']:>2}x  {row['skill']} "
                f"({row['category']}, {row['estimate']})"
            )
    else:
        lines.append("Sem lacunas — você cobre as skills em alta.")
    if have:
        aligned = ", ".join(f"{skill}({count})" for skill, count in have[:10])
        lines.append(f"Já alinhado: {aligned}")
    return "\n".join(lines)


def format_trend(trend_rows: list[dict], limit: int = 10) -> str:
    lines = ["<b>Tendência (recente vs anterior)</b>"]
    if not trend_rows:
        lines.append("(histórico insuficiente — precisa de >=2 meses de coletas)")
        return "\n".join(lines)
    rising = [row for row in trend_rows if row["delta"] > 0][:limit]
    falling = [row for row in trend_rows if row["delta"] < 0][-limit:]
    if rising:
        lines.append("Subindo:")
        for row in rising:
            lines.append(
                f"  +{row['delta']}  {row['skill']} ({row['prior']}->{row['recent']})"
            )
    if falling:
        lines.append("Caindo:")
        for row in falling:
            lines.append(
                f"  {row['delta']}  {row['skill']} ({row['prior']}->{row['recent']})"
            )
    return "\n".join(lines)


def format_full_report(
    aggregate: list[tuple[str, int]],
    have: list[tuple[str, int]],
    missing_enriched: list[dict],
    trend_rows: list[dict],
    role: str,
    days: int,
) -> str:
    """Relatório completo (agregado + gap + tendência) p/ Telegram/console."""
    return "\n\n".join(
        [
            format_aggregate(aggregate, role, days),
            format_gap(have, missing_enriched),
            format_trend(trend_rows),
        ]
    )
