import os
import json
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

LOCAL_DIR = str(_PROJECT_ROOT / ".local")
BOT_PROFILE_DIR = str(_PROJECT_ROOT / ".local" / "bot_profile")
LAST_URLS_FILE = str(_PROJECT_ROOT / ".local" / "files" / "last_urls.json")


def _find_resume(hint: str = "") -> str:
    if hint and os.path.exists(hint):
        return hint
    if not os.path.isdir(LOCAL_DIR):
        return hint or "resume.txt"
    if hint:
        p = os.path.join(LOCAL_DIR, hint)
        if os.path.exists(p):
            return p
    for f in os.listdir(LOCAL_DIR):
        if f.lower().endswith((".pdf", ".txt")) and ("curriculo" in f.lower() or "resume" in f.lower() or "cv" in f.lower()):
            return os.path.join(LOCAL_DIR, f)
    for ext in (".pdf", ".txt"):
        for f in os.listdir(LOCAL_DIR):
            if f.lower().endswith(ext):
                return os.path.join(LOCAL_DIR, f)
    return hint or "resume.txt"


def load_last_urls() -> dict:
    if os.path.exists(LAST_URLS_FILE):
        with open(LAST_URLS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_last_url(task: str, url: str, page: int = 1, extra: dict | None = None):
    urls = load_last_urls()
    entry = {"url": url, "page": page}
    if extra:
        entry.update(extra)

    history_key = f"{task}_history"
    old = urls.get(task)
    if old and isinstance(old, dict) and old.get("url") != url:
        history = urls.get(history_key, [])
        history = [old] + [h for h in history if h.get("url") != old.get("url")]
        urls[history_key] = history[:3]

    urls[task] = entry
    with open(LAST_URLS_FILE, "w") as f:
        json.dump(urls, f, indent=2)


def current_week() -> str:
    return date.today().strftime("%Y-W%W")


def today_str() -> str:
    return date.today().isoformat()


def is_already_ran_today() -> bool:
    data = load_last_urls()
    return data.get("connect_last_run_date") == today_str()


def save_ran_today():
    data = load_last_urls()
    data["connect_last_run_date"] = today_str()
    with open(LAST_URLS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def is_weekly_limit_reached() -> bool:
    data = load_last_urls()
    return data.get("connect_weekly_limit_week") == current_week()


def save_weekly_limit_reached():
    data = load_last_urls()
    data["connect_weekly_limit_week"] = current_week()
    with open(LAST_URLS_FILE, "w") as f:
        json.dump(data, f, indent=2)
