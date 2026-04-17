import json
import asyncio
import re
from datetime import date
from pathlib import Path
from src.core.ai.llm_provider import get_eval_provider
from src.config.settings import logger

_SKILLS_FILE = Path(__file__).parent.parent.parent.parent / "files" / "skills_gap.json"

CATEGORIES = ["python", "node", "frontend", "devops", "data", "general"]


def load_skills() -> dict:
    try:
        if _SKILLS_FILE.exists():
            with open(_SKILLS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_skills(skills: dict) -> None:
    try:
        _SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SKILLS_FILE, "w", encoding="utf-8") as f:
            json.dump(skills, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save skills_gap.json: {e}")


async def _assess_skill_async(skill: str) -> dict:
    """Ask AI to assess a skill's category, learning level and time estimate."""
    prompt = f"""Classify the following technical skill for a software developer who wants to learn it.

SKILL: {skill}

Reply with ONLY one line in this exact format:
<category>|<level>|<estimate>

Where:
- category: one of: python, node, frontend, devops, data, general
  - python: specific to Python ecosystem (FastAPI, Celery, SQLAlchemy, etc.)
  - node: specific to Node.js ecosystem (NestJS, Prisma, Express, etc.)
  - frontend: UI frameworks/tools (React, Vue, Angular, etc.)
  - devops: infrastructure/ops (Terraform, Kubernetes, Helm, etc.)
  - data: data engineering (Spark, Airflow, dbt, Kafka, etc.)
  - general: applies to any stack (AWS, Docker, DDD, TDD, Redis, CI/CD, etc.)
- level: integer 1-5 (1=days/hours, 2=1-2 weeks, 3=1-3 months, 4=3-12 months, 5=1+ year)
- estimate: human-readable time range in Portuguese (e.g. "1-2 semanas", "3-6 meses", "1-2 dias")

Examples:
general|4|6-12 meses
python|2|1-2 semanas
frontend|3|1-3 meses
devops|4|3-6 meses"""

    try:
        result = await get_eval_provider().complete(prompt)
        for line in result.splitlines():
            line = line.strip()
            parts = line.split("|")
            if len(parts) == 3:
                category = parts[0].strip().lower()
                if category not in CATEGORIES:
                    category = "general"
                try:
                    level = max(1, min(5, int(re.sub(r"\D", "", parts[1]))))
                except Exception:
                    level = 3
                estimate = parts[2].strip()
                return {"category": category, "level": level, "estimate": estimate}
    except Exception as e:
        logger.warning(f"Could not assess skill '{skill}': {e}")

    return {"category": "general", "level": 3, "estimate": "desconhecido"}


_NULL_SKILLS = {"none", "null", "nenhum", "nenhuma", "n/a", "não sei", "nao sei"}

_SKILL_SUFFIXES = [" knowledge", " experience", " cloud", " fluente", " fluent"]
_SKILL_CANONICAL: dict[str, str] = {
    "springboot": "spring boot",
    "machine-learning": "machine learning",
    "data-science": "data science",
    "cloud-architecture": "cloud architecture",
    "small-language-models": "small language models",
    "kafka/sqs/sns": "kafka",
}


def _canonical_skill(skill: str) -> str:
    s = skill.lower().strip()
    s = re.sub(r"\s*\(.*?\)", "", s)     # remove parentheses: "aws (s3/...)" → "aws"
    s = re.sub(r"[-_/]", " ", s)         # hyphens/slashes to spaces
    s = re.sub(r"\s+", " ", s).strip()
    for suffix in _SKILL_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    return _SKILL_CANONICAL.get(s, s)


async def track_missing_skills_async(missing: list[str]) -> None:
    if not missing:
        return

    # Filter null values and normalize to canonical names
    cleaned = []
    for s in missing:
        if s.lower().strip() in _NULL_SKILLS:
            continue
        canonical = _canonical_skill(s)
        if canonical and canonical not in _NULL_SKILLS:
            cleaned.append(canonical)

    if not cleaned:
        return

    skills = load_skills()
    today = date.today().isoformat()

    new_skills = [s for s in cleaned if s not in skills]

    if new_skills:
        assessments = await asyncio.gather(*[_assess_skill_async(s) for s in new_skills])
        for skill, assessment in zip(new_skills, assessments):
            skills[skill] = {**assessment, "count": 1, "last_seen": today}
            logger.info(f"New skill tracked: '{skill}' — {assessment['category']} level={assessment['level']} ({assessment['estimate']})")

    for skill in cleaned:
        if skill in skills and skill not in new_skills:
            skills[skill]["count"] = skills[skill].get("count", 0) + 1
            skills[skill]["last_seen"] = today

    save_skills(skills)


def track_missing_skills(missing: list[str]) -> None:
    if missing:
        asyncio.run(track_missing_skills_async(missing))
