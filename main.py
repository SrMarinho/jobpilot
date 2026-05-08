import os
import json
import time
import asyncio
import sys
from datetime import date
from enum import Enum
from pathlib import Path as _Path
from typing import Optional, List

import typer

import src.config.settings as setting
import undetected_chromedriver as uc
from src.automation.tasks.connection_manager import ConnectionManager
from src.automation.tasks.job_application_manager import JobApplicationManager, _detect_site
from src.config.settings import logger
from dotenv import load_dotenv

BOT_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "bot_profile")
LAST_URLS_FILE = os.path.join(os.path.dirname(__file__), "files", "last_urls.json")


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


def get_config(force_headless: bool = False) -> dict:
    env_headless = str(os.getenv("HEADLESS")).upper()
    headless = force_headless or (False if env_headless == "FALSE" else True)
    return {"headless": headless}


def setup(force_headless: bool = False) -> uc.Chrome:
    config = get_config(force_headless)
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options, headless=config["headless"], version_main=146)
    if not config["headless"]:
        driver.maximize_window()
    return driver


LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "glassdoor": "https://www.glassdoor.com/profile/login_input.htm",
    "indeed": "https://secure.indeed.com/auth",
}

SITE_DOMAINS = {
    "linkedin":  [".linkedin.com"],
    "glassdoor": [".glassdoor.com"],
    "indeed":    [".indeed.com", ".secure.indeed.com"],
}


SKILLS_FILE = os.path.join(os.path.dirname(__file__), "files", "skills_gap.json")
QA_FILE = os.path.join(os.path.dirname(__file__), "files", "qa.json")

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


def _load_qa_cli() -> dict:
    if os.path.exists(QA_FILE):
        with open(QA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_qa_cli(qa: dict):
    os.makedirs(os.path.dirname(QA_FILE), exist_ok=True)
    with open(QA_FILE, "w", encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=2)


def _qa_display(key: str, entry) -> tuple[str, str, str | None]:
    if isinstance(entry, dict):
        original = entry.get("original") or key
        answer   = entry.get("answer") or ""
        options  = entry.get("options")
        opts_str = ", ".join(options) if options else None
    else:
        original = key
        answer   = str(entry) if entry is not None else ""
        opts_str = None
    return original, answer, opts_str


def _qa_all_entries(qa: dict) -> list[tuple[str, object]]:
    return list(qa.items())


def _is_answered(entry) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("answer", "").strip())
    return bool(str(entry).strip()) if entry is not None else False


def run_answers_list():
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    missing = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if not missing:
        print("All questions have answers.")
        return
    print(f"{len(missing)} question(s) without an answer:\n")
    for num, key, entry in missing:
        original, _, opts_str = _qa_display(key, entry)
        print(f"  [{num}] {original}")
        if opts_str:
            print(f"       Options: {opts_str}")
    print('\nUse: answers set <number> "your answer"')


def run_answers_show():
    qa = _load_qa_cli()
    if not qa:
        print("No cached answers found.")
        return
    entries = _qa_all_entries(qa)
    answered   = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if     _is_answered(v)]
    unanswered = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if answered:
        print(f"Answered ({len(answered)}):\n")
        for num, key, entry in answered:
            original, answer, opts_str = _qa_display(key, entry)
            print(f"  [{num}] {original}")
            print(f"        A: {answer}")
            if opts_str:
                print(f"        Options: {opts_str}")
    if unanswered:
        print(f"\nMissing ({len(unanswered)}):\n")
        for num, key, entry in unanswered:
            original, _, opts_str = _qa_display(key, entry)
            print(f"  [{num}] {original}")
            if opts_str:
                print(f"        Options: {opts_str}")
        print('\nUse: answers set <number> "your answer"')


def run_answers_set(number: int, answer: str):
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    if number < 1 or number > len(entries):
        print(f"Invalid number {number}. Valid range: 1–{len(entries)}.")
        return
    key, entry = entries[number - 1]
    original, old_answer, _ = _qa_display(key, entry)
    if isinstance(entry, dict):
        entry["answer"] = answer
        qa[key] = entry
    else:
        qa[key] = answer
    _save_qa_cli(qa)
    print(f"[{number}] {original}")
    print(f"  {old_answer!r} -> {answer!r}")


def run_answers_fill():
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    missing = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if not missing:
        print("All questions already have answers.")
        return
    print(f"{len(missing)} question(s) to fill. Press Enter to skip.\n")
    for num, key, entry in missing:
        original, _, opts_str = _qa_display(key, entry)
        print(f"[{num}] {original}")
        if opts_str:
            print(f"     Options: {opts_str}")
        try:
            value = input("     Answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            break
        if not value:
            print("     Skipped.\n")
            continue
        if isinstance(entry, dict):
            entry["answer"] = value
            qa[key] = entry
        else:
            qa[key] = value
        _save_qa_cli(qa)
        print("     Saved.\n")


def run_answers_clear():
    _save_qa_cli({})
    print("All cached answers cleared.")


ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

_PROVIDER_KEYS = {
    "llm":  ("LLM_PROVIDER",      "LANGCHAIN_MODEL",      "CLAUDE_MODEL"),
    "eval": ("LLM_PROVIDER_EVAL", "LANGCHAIN_MODEL_EVAL", "CLAUDE_MODEL"),
}

_CLAUDE_DEFAULT  = "claude-haiku-4-5-20251001"
_OLLAMA_DEFAULT  = "llama3.1:8b"


def run_provider_show():
    from dotenv import dotenv_values
    cfg = dotenv_values(ENV_FILE)

    def _fmt(provider_key: str, lc_model_key: str, _: str) -> str:
        backend = cfg.get(provider_key, "(not set)").lower()
        if backend == "langchain":
            model = cfg.get(lc_model_key, "(not set)")
            return f"langchain  model={model}"
        if backend == "claude":
            model = cfg.get("CLAUDE_MODEL", _CLAUDE_DEFAULT)
            return f"claude     model={model}"
        return backend

    print(f"  llm  (form Q&A):       {_fmt(*_PROVIDER_KEYS['llm'])}")
    print(f"  eval (job evaluation): {_fmt(*_PROVIDER_KEYS['eval'])}")


def run_provider_set(target: str, backend: str, model: str | None):
    from dotenv import set_key
    provider_key, lc_model_key, _ = _PROVIDER_KEYS[target]

    set_key(ENV_FILE, provider_key, backend)

    if backend == "langchain":
        m = model or _OLLAMA_DEFAULT
        set_key(ENV_FILE, lc_model_key, m)
        print(f"[provider] {target} -> langchain  model={m}")
    else:
        if model:
            set_key(ENV_FILE, "CLAUDE_MODEL", model)
        m = model or os.getenv("CLAUDE_MODEL") or _CLAUDE_DEFAULT
        print(f"[provider] {target} -> claude     model={m}")


def run_logout(site: str):
    domains = SITE_DOMAINS[site]
    login_url = LOGIN_URLS[site]
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options, headless=False, version_main=146)
    try:
        driver.get(login_url)
        time.sleep(2)
        removed = 0
        all_cookies = driver.get_cookies()
        for cookie in all_cookies:
            domain = cookie.get("domain", "")
            if any(domain.endswith(d.lstrip(".")) or domain == d for d in domains):
                try:
                    driver.delete_cookie(cookie["name"])
                    removed += 1
                except Exception:
                    pass
        print(f"Cleared {removed} cookie(s) for {site}.")
        print(f"Session removed. Run 'login {site}' to log in again.")
    finally:
        driver.quit()


def run_login(site: str):
    url = LOGIN_URLS[site]
    options = uc.ChromeOptions()
    options.add_argument(f"--user-data-dir={BOT_PROFILE_DIR}")
    options.add_argument("--start-maximized")
    driver = uc.Chrome(options=options, headless=False, version_main=146)
    driver.get(url)
    print(f"Browser opened at {url}")
    print("Log in and close the browser window when done.")
    while True:
        try:
            _ = driver.window_handles
            time.sleep(1)
        except Exception:
            break
    print("Browser closed. Login session saved.")


# ── Typer CLI ─────────────────────────────────────────────────────────────────

class SiteName(str, Enum):
    linkedin = "linkedin"
    glassdoor = "glassdoor"
    indeed = "indeed"


class LLMBackend(str, Enum):
    claude = "claude"
    langchain = "langchain"


class ProviderTarget(str, Enum):
    llm = "llm"
    eval = "eval"


class SkillCategory(str, Enum):
    python = "python"
    node = "node"
    frontend = "frontend"
    devops = "devops"
    data = "data"
    general = "general"


app = typer.Typer(help="JobPilot \u2014 Automated job application bot")
skills_app = typer.Typer(help="View missing skills detected during job evaluation")
answers_app = typer.Typer(help="Manage cached form answers (files/qa.json)")
provider_app = typer.Typer(help="Show or change LLM provider settings")

app.add_typer(skills_app, name="skills")
app.add_typer(answers_app, name="answers")
app.add_typer(provider_app, name="provider")


@app.callback()
def _callback(
    ctx: typer.Context,
    headless: bool = typer.Option(False, "--headless", help="Force headless Chrome (overrides HEADLESS env var)"),
):
    ctx.ensure_object(dict)
    ctx.obj["headless"] = headless


# ── login / logout ─────────────────────────────────────────────────────────────

@app.command()
def login(site: SiteName):
    """Open browser to log in to a job site (linkedin, glassdoor, indeed)."""
    run_login(site.value)


@app.command()
def logout(site: SiteName):
    """Clear saved session for a site."""
    run_logout(site.value)


# ── apply ──────────────────────────────────────────────────────────────────────

def _resolve_apply_url_task(
    url: str | None,
    resume_from: bool,
    site_name: str | None,
    resume_path_arg: str | None,
) -> tuple[str, int, str, str]:
    last_urls = load_last_urls()

    if url:
        site_key = f"apply_{_detect_site(url)}"
    else:
        explicit_site = site_name
        if explicit_site:
            site_key = f"apply_{explicit_site}"
        else:
            site_key = f"apply_{last_urls.get('apply_last_site', 'linkedin')}"

    saved: dict = last_urls.get(site_key, {})
    if isinstance(saved, str):
        saved = {"url": saved, "page": 1}

    start_page = 1
    if not url:
        url = saved.get("url") if isinstance(saved, dict) else None
        if not url:
            print(f"Error: --url is required for the first 'apply' run (no saved URL found for {site_key}).")
            raise typer.Exit()

        if resume_from:
            start_page = saved.get("page", 1)
            print(f"Resuming '{site_key}' from page {start_page}: {url}")
        else:
            print(f"Using last saved URL for '{site_key}': {url}")

    resolved_resume: str = (
        resume_path_arg
        or (saved.get("resume") if isinstance(saved, dict) else None)
        or last_urls.get("default_resume")
        or "resume.txt"
    )

    return url, start_page, site_key, resolved_resume


def _resolve_saved_options(saved: dict) -> tuple[list[str], str, str | None, str | None, str | None, str | None]:
    level: list[str] = saved.get("level", []) if isinstance(saved, dict) else []
    preferences: str = saved.get("preferences", "") if isinstance(saved, dict) else ""
    llm_prov = saved.get("llm_provider") if isinstance(saved, dict) else None
    llm_mod = saved.get("llm_model") if isinstance(saved, dict) else None
    eval_prov = saved.get("eval_provider") if isinstance(saved, dict) else None
    eval_mod = saved.get("eval_model") if isinstance(saved, dict) else None
    return level, preferences, llm_prov, llm_mod, eval_prov, eval_mod


@app.command(epilog="Parameters are saved per site and restored automatically on next run.")
def apply(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Job search URL (first run only, saved for later)"),
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Path to resume PDF or TXT (default: resume.txt)"),
    preferences: str = typer.Option("", "--preferences", "-p", help="Preferences to guide evaluation"),
    level: List[str] = typer.Option([], "--level", "-l", help="Accepted seniority levels (repeat: --level junior --level pleno)"),
    start_page: Optional[int] = typer.Option(None, "--start-page", help="Page to start from (default: 1)"),
    max_pages: int = typer.Option(100, "--max-pages", help="Max pages to process (default: 100)"),
    max_applications: int = typer.Option(0, "--max-applications", metavar="N", help="Stop after N applications (default: 0 = unlimited)"),
    resume_from: bool = typer.Option(False, "--continue", help="Resume from the last page where it stopped"),
    site_name: Optional[str] = typer.Option(None, "--site", help="Resume saved config for a specific site: linkedin, glassdoor, indeed"),
    llm_provider: Optional[str] = typer.Option(None, "--llm-provider", help="Override LLM provider for this run: claude or langchain"),
    llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Override LLM model for this run"),
    eval_provider: Optional[str] = typer.Option(None, "--eval-provider", help="Override eval provider for this run: claude or langchain"),
    eval_model: Optional[str] = typer.Option(None, "--eval-model", help="Override eval model for this run"),
    no_save: bool = typer.Option(False, "--no-save", help="Run without overwriting the saved URL/config for this site"),
    no_submit: bool = typer.Option(False, "--no-submit", help="Fill forms but do not submit (for testing)"),
):
    """Apply to jobs via Easy Apply (LinkedIn, Glassdoor, Indeed)."""
    headless = ctx.obj.get("headless", False)
    resolved_url, resolved_start_page, site_key, resolved_resume = _resolve_apply_url_task(
        url, resume_from, site_name, resume,
    )

    last_urls = load_last_urls()
    saved = last_urls.get(site_key, {})

    # Merge: CLI args > saved > defaults
    final_level = level or _resolve_saved_options(saved)[0]
    final_preferences = preferences or _resolve_saved_options(saved)[1]
    final_llm_prov = llm_provider or _resolve_saved_options(saved)[2]
    final_llm_mod = llm_model or _resolve_saved_options(saved)[3]
    final_eval_prov = eval_provider or _resolve_saved_options(saved)[4]
    final_eval_mod = eval_model or _resolve_saved_options(saved)[5]

    if final_level:
        print(f"Level filter: {final_level}")
    if final_preferences:
        print(f"Preferences: {final_preferences}")
    if final_eval_prov:
        print(f"Eval provider: {final_eval_prov}" + (f" model={final_eval_mod}" if final_eval_mod else ""))

    # Warmup LLM
    if final_llm_prov:
        os.environ["LLM_PROVIDER"] = final_llm_prov
        logger.info(f"[override] LLM_PROVIDER={final_llm_prov}")
    if final_llm_mod:
        key = "LANGCHAIN_MODEL" if os.environ.get("LLM_PROVIDER") == "langchain" else "CLAUDE_MODEL"
        os.environ[key] = final_llm_mod
        logger.info(f"[override] {key}={final_llm_mod}")
    if final_eval_prov:
        os.environ["LLM_PROVIDER_EVAL"] = final_eval_prov
        logger.info(f"[override] LLM_PROVIDER_EVAL={final_eval_prov}")
    if final_eval_mod:
        key = "LANGCHAIN_MODEL_EVAL" if os.environ.get("LLM_PROVIDER_EVAL") == "langchain" else "CLAUDE_MODEL"
        os.environ[key] = final_eval_mod
        logger.info(f"[override] {key}={final_eval_mod}")

    from src.core.ai.llm_provider import get_llm_provider, get_eval_provider
    logger.info("Warming up LLM models...")

    async def _warmup():
        async def _try(name: str, provider):
            try:
                await provider.complete("hi")
                logger.info(f"Warmup OK: {name}")
            except Exception as e:
                logger.warning(f"Warmup failed for {name}: {e}")
        await asyncio.gather(
            _try("llm", get_llm_provider()),
            _try("eval", get_eval_provider()),
        )
    asyncio.run(_warmup())
    logger.info("LLM models ready.")

    # Save URL if new
    if url and not no_save:
        extra = {
            "level": final_level, "preferences": final_preferences, "resume": resolved_resume,
            "llm_provider": final_llm_prov, "llm_model": final_llm_mod,
            "eval_provider": final_eval_prov, "eval_model": final_eval_mod,
        }
        save_last_url(site_key, resolved_url, page=1, extra=extra)
        data = load_last_urls()
        data["apply_last_site"] = _detect_site(resolved_url)
        if resume:
            data["default_resume"] = resume
        with open(LAST_URLS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    def on_page_change(page: int):
        if no_save:
            return
        extra = {
            "level": final_level, "preferences": final_preferences, "resume": resolved_resume,
            "llm_provider": final_llm_prov, "llm_model": final_llm_mod,
            "eval_provider": final_eval_prov, "eval_model": final_eval_mod,
        }
        save_last_url(site_key, resolved_url, page=page, extra=extra)

    driver = setup(force_headless=headless)
    try:
        JobApplicationManager(
            driver,
            url=resolved_url,
            resume_path=resolved_resume,
            preferences=final_preferences,
            level=final_level,
            max_pages=max_pages,
            max_applications=max_applications,
            start_page=resolved_start_page if resume_from else (start_page or 1),
            on_page_change=on_page_change,
            no_submit=no_submit,
        ).run()
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
    except Exception as e:
        logger.critical(f"{str(e)}")
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ── connect ────────────────────────────────────────────────────────────────────

@app.command()
def connect(
    ctx: typer.Context,
    url: Optional[str] = typer.Option(None, "--url", "-u", help="LinkedIn people search URL (uses last saved if omitted)"),
    start_page: Optional[int] = typer.Option(None, "--start-page", help="Page to start from (default: 1)"),
    max_pages: int = typer.Option(100, "--max-pages", help="Max pages to process (default: 100)"),
    resume: bool = typer.Option(False, "--continue", help="Resume from the last page where it stopped"),
    scheduled: bool = typer.Option(False, "--scheduled", help="Scheduled mode: skip if already ran today or weekly limit reached"),
):
    """Send connection requests (LinkedIn people search)."""
    headless = ctx.obj.get("headless", False)
    last_urls = load_last_urls()
    site_key = "connect"
    saved: dict = last_urls.get(site_key, {})

    if scheduled:
        if is_already_ran_today():
            logger.info("Already ran today. Skipping.")
            return
        if is_weekly_limit_reached():
            logger.info("Weekly connection limit already reached this week. Skipping.")
            return
        save_ran_today()

    resolved_url = url
    resolved_start_page = start_page or 1
    if not resolved_url:
        resolved_url = saved.get("url") if isinstance(saved, dict) else None
        if not resolved_url:
            print("Error: --url is required for the first 'connect' run (no saved URL found).")
            raise typer.Exit()
        if resume:
            resolved_start_page = saved.get("page", 1) if isinstance(saved, dict) else 1
            print(f"Resuming 'connect' from page {resolved_start_page}: {resolved_url}")
        else:
            print(f"Using last saved URL for 'connect': {resolved_url}")

    if resolved_url:
        save_last_url(site_key, resolved_url, page=1)

    def on_page_change(page: int):
        save_last_url(site_key, resolved_url, page=page)

    driver = setup(force_headless=headless)
    try:
        from src.core.use_cases.monthly_report import save_connections
        manager = ConnectionManager(
            driver, url=resolved_url,
            max_pages=max_pages, start_page=resolved_start_page,
            on_page_change=on_page_change,
        )
        manager.run()
        sent = manager.connect_people.invite_sended
        if sent:
            save_connections(sent)
        if manager.connect_people.limit_reached:
            save_weekly_limit_reached()
            logger.info("Weekly limit reached \u2014 saved. Will skip until next week.")
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
    except Exception as e:
        logger.critical(f"{str(e)}")
        try:
            driver.save_screenshot(f"{setting.screenshots_path}.png")
        except Exception:
            pass
        raise
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ── test-apply ─────────────────────────────────────────────────────────────────

@app.command("test-apply")
def test_apply(
    ctx: typer.Context,
    job_url: str = typer.Argument(..., help="LinkedIn job URL (e.g. https://www.linkedin.com/jobs/view/1234567890)"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Path to resume file (default: resume.txt)"),
    no_submit: bool = typer.Option(False, "--no-submit", help="Fill forms but do not submit"),
):
    """Test Easy Apply on a specific job URL (skips evaluation)."""
    from src.core.use_cases.job_application_handler import JobApplicationHandler

    resume_path = resume or "resume.txt"
    rp = _Path(resume_path)
    if rp.suffix.lower() == ".pdf":
        from pypdf import PdfReader as _PdfReader
        resume_text = "\n".join(p.extract_text() or "" for p in _PdfReader(resume_path).pages)
    else:
        resume_text = rp.read_text(encoding="utf-8")

    driver = setup(force_headless=False)
    try:
        driver.get(job_url)
        time.sleep(3)
        from src.automation.pages.jobs_search_page import JobsSearchPage
        page = JobsSearchPage(driver, job_url)
        btn = page.get_easy_apply_btn()
        if not btn:
            print("No Easy Apply button found on this job page.")
            return
        title = page.get_job_title() or "Test Job"
        description = page.get_job_description() or ""
        print(f"Applying to: {title}")
        btn.click()
        time.sleep(1.5)
        handler = JobApplicationHandler(driver, resume=resume_text)
        success = handler.submit_easy_apply(job_title=title, job_description=description, no_submit=no_submit)
        if no_submit:
            print("Dry run complete \u2014 form was filled but not submitted.")
        else:
            print(f"Result: {'SUCCESS' if success else 'FAILED'}")
    finally:
        try:
            input("Press Enter to close browser...")
        except EOFError:
            pass
        driver.quit()


# ── bot ────────────────────────────────────────────────────────────────────────

@app.command()
def bot(
    resume: str = typer.Option("resume.txt", "--resume", help="Path to resume file (default: resume.txt)"),
):
    """Start Telegram bot to control JobPilot remotely."""
    from src.bot.telegram_bot import TelegramBot
    TelegramBot(driver_factory=setup, resume_path=resume).run()


# ── report ─────────────────────────────────────────────────────────────────────

@app.command()
def report(
    month: Optional[str] = typer.Option(None, "--month", metavar="YYYY-MM", help="Specific month (e.g. 2025-03)"),
    prev: bool = typer.Option(False, "--prev", help="Report for the previous month"),
    year: Optional[int] = typer.Option(None, "--year", metavar="YYYY", help="Annual summary for the given year (e.g. 2026)"),
    telegram: bool = typer.Option(False, "--telegram", help="Send report via Telegram in addition to printing"),
    scheduled: bool = typer.Option(False, "--scheduled", help="Scheduled mode: send via Telegram only once per month"),
):
    """Generate and print monthly report (default: current month)."""
    from datetime import date as _date
    from src.core.use_cases.monthly_report import (
        generate_report, generate_year_report, _save_report,
        _format_report, _format_year_report, _prev_month,
        run_monthly_report_scheduled,
    )

    def _print(text: str):
        sys.stdout.buffer.write((text.replace("<b>", "").replace("</b>", "") + "\n").encode("utf-8", "replace"))

    if scheduled:
        run_monthly_report_scheduled()
    elif year:
        rep = generate_year_report(year)
        _save_report(rep)
        if telegram:
            from src.utils.telegram import send_telegram
            send_telegram(_format_year_report(rep))
        _print(_format_year_report(rep))
    else:
        today = _date.today()
        if prev:
            yr, mo = _prev_month(today)
        elif month:
            try:
                yr, mo = map(int, month.split("-"))
            except ValueError:
                print("Invalid --month format. Use YYYY-MM")
                return
        else:
            yr, mo = today.year, today.month
        rep = generate_report(yr, mo)
        _save_report(rep)
        if telegram:
            from src.utils.telegram import send_telegram
            send_telegram(_format_report(rep))
        _print(_format_report(rep))


# ── skills ─────────────────────────────────────────────────────────────────────

@skills_app.command("list")
def skills_list(
    category: Optional[SkillCategory] = typer.Option(None, "--category", help="Filter by category"),
    level: Optional[int] = typer.Option(None, "--level", min=1, max=5, help="Filter by learning level (1=fast, 5=slow)"),
):
    """List all missing skills sorted by frequency."""
    run_skills_list(category.value if category else None, level)


@skills_app.command("top")
def skills_top(
    n: int = typer.Option(10, "--n", help="Number of skills to show (default: 10)"),
    category: Optional[SkillCategory] = typer.Option(None, "--category", help="Filter by category"),
):
    """Show top most demanded missing skills."""
    run_skills_top(n, category.value if category else None)


@skills_app.command("clear")
def skills_clear():
    """Clear all tracked skills."""
    run_skills_clear()


# ── answers ────────────────────────────────────────────────────────────────────

@answers_app.command("list")
def answers_list():
    """Show questions with missing answers (numbered)."""
    run_answers_list()


@answers_app.command("show")
def answers_show():
    """Show all cached answers (numbered)."""
    run_answers_show()


@answers_app.command("fill")
def answers_fill():
    """Interactively answer all missing questions one by one."""
    run_answers_fill()


@answers_app.command("set")
def answers_set(
    number: int = typer.Argument(..., help="Question number shown in 'answers list' or 'answers show'"),
    answer: str = typer.Argument(..., help="Answer to save"),
):
    """Set an answer by question number (from list/show)."""
    run_answers_set(number, answer)


@answers_app.command("clear")
def answers_clear():
    """Remove all cached answers."""
    run_answers_clear()


# ── provider ───────────────────────────────────────────────────────────────────

@provider_app.command("show")
def provider_show():
    """Show current provider configuration."""
    run_provider_show()


@provider_app.command("set")
def provider_set(
    target: ProviderTarget = typer.Argument(..., help="Which provider to change: 'llm' (form Q&A) or 'eval' (job evaluation)"),
    backend: LLMBackend = typer.Argument(..., help="Backend to use: claude or langchain"),
    model: Optional[str] = typer.Option(None, "--model", help="Model name (e.g. claude-haiku-4-5-20251001 or llama3.1:8b)"),
):
    """Set a provider (claude or langchain)."""
    run_provider_set(target.value, backend.value, model)


def main():
    app()


if __name__ == "__main__":
    load_dotenv()
    main()
