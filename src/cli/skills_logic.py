import os
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILLS_FILE = str(_PROJECT_ROOT / ".local" / "files" / "skills_gap.json")

_LEVEL_LABELS = {1: "dias", 2: "semanas", 3: "1-3 meses", 4: "3-12 meses", 5: "1+ ano"}
_CATEGORY_COLORS = {"python": "Python", "node": "Node", "frontend": "Frontend",
                    "devops": "DevOps", "data": "Data", "general": "General"}


def _load_skills_cli() -> dict:
    if os.path.exists(SKILLS_FILE):
        with open(SKILLS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def run_skills_list(category: str | None, level: int | None):
    skills = _load_skills_cli()
    if not skills:
        print("No skills tracked yet. Run apply to start collecting data.")
        return
    entries = [
        (name, data) for name, data in skills.items()
        if (category is None or data.get("category") == category)
        and (level is None or data.get("level") == level)
    ]
    if not entries:
        print("No skills match the given filters.")
        return
    entries.sort(key=lambda x: x[1].get("count", 0), reverse=True)
    print(f"{'Skill':<25} {'Category':<12} {'Level':<7} {'Estimate':<15} {'Count'}")
    print("-" * 72)
    for name, data in entries:
        cat   = data.get("category", "?")
        lvl   = data.get("level", "?")
        est   = data.get("estimate", "?")
        count = data.get("count", 0)
        stars = "*" * lvl if isinstance(lvl, int) else "?"
        print(f"  {name:<23} {cat:<12} {stars:<7} {est:<15} {count}x")


def run_skills_top(n: int, category: str | None):
    skills = _load_skills_cli()
    if not skills:
        print("No skills tracked yet.")
        return
    entries = [
        (name, data) for name, data in skills.items()
        if category is None or data.get("category") == category
    ]
    entries.sort(key=lambda x: x[1].get("count", 0), reverse=True)
    entries = entries[:n]
    label = f" [{category}]" if category else ""
    print(f"Top {len(entries)} missing skills{label}:\n")
    for i, (name, data) in enumerate(entries, 1):
        lvl   = data.get("level", "?")
        est   = data.get("estimate", "?")
        count = data.get("count", 0)
        stars = "*" * lvl if isinstance(lvl, int) else "?"
        cat   = data.get("category", "?")
        print(f"  {i:>2}. {name:<22} {cat:<12} {stars:<7} {est}  ({count}x)")


def run_skills_clear():
    if os.path.exists(SKILLS_FILE):
        with open(SKILLS_FILE, "w") as f:
            json.dump({}, f)
    print("Skills gap cleared.")
