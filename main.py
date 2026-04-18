import os
import json
import time
import argparse
from datetime import date
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


def parse_args():
    parser = argparse.ArgumentParser(description="JobPilot")
    parser.add_argument("--headless", action="store_true", help="Force headless Chrome (overrides HEADLESS env var)")
    subparsers = parser.add_subparsers(dest="task", required=True)

    login_parser = subparsers.add_parser("login", help="Open browser to log in to a job site")
    login_parser.add_argument(
        "site",
        choices=list(LOGIN_URLS.keys()),
        help="Site to log in to: linkedin, glassdoor, indeed",
    )

    logout_parser = subparsers.add_parser("logout", help="Clear saved session for a site")
    logout_parser.add_argument(
        "site",
        choices=list(LOGIN_URLS.keys()),
        help="Site to log out from: linkedin, glassdoor, indeed",
    )

    connect_parser = subparsers.add_parser("connect", help="Send connection requests")
    connect_parser.add_argument("--url", type=str, default=None, help="LinkedIn people search URL (uses last saved URL if omitted)")
    connect_parser.add_argument("--start-page", type=int, default=None, help="Page to start from (default: 1)")
    connect_parser.add_argument("--max-pages", type=int, default=100, help="Max pages to process (default: 100)")
    connect_parser.add_argument("--continue", dest="resume", action="store_true", help="Resume from the last page where it stopped")
    connect_parser.add_argument("--scheduled", action="store_true", help="Scheduled mode: skip if already ran today or weekly limit reached")

    apply_parser = subparsers.add_parser("apply", help="Apply to jobs via Easy Apply")
    apply_parser.add_argument("--url", type=str, default=None, help="Job search URL (uses last saved URL if omitted)")
    apply_parser.add_argument("--resume", type=str, default=None, help="Path to resume file (default: resume.txt)")
    apply_parser.add_argument("--preferences", type=str, default="", help="Job preferences to guide evaluation")
    apply_parser.add_argument("--level", type=str, nargs="+", default=[], help="Accepted seniority levels (e.g. --level junior pleno)")
    apply_parser.add_argument("--start-page", type=int, default=None, help="Page to start from (default: 1)")
    apply_parser.add_argument("--max-pages", type=int, default=100, help="Max pages to process (default: 100)")
    apply_parser.add_argument("--max-applications", type=int, default=0, metavar="N", help="Stop after applying to N jobs (default: 0 = unlimited)")
    apply_parser.add_argument("--continue", dest="resume_from", action="store_true", help="Resume from the last page where it stopped")
    apply_parser.add_argument("--site", choices=["linkedin", "glassdoor", "indeed"], default=None, help="Resume saved config for a specific site (default: last used site)")
    apply_parser.add_argument("--llm-provider", choices=["claude", "langchain"], default=None, metavar="BACKEND", help="Override LLM provider for this run only (claude or langchain)")
    apply_parser.add_argument("--llm-model", type=str, default=None, metavar="MODEL", help="Override LLM model for this run only")
    apply_parser.add_argument("--eval-provider", choices=["claude", "langchain"], default=None, metavar="BACKEND", help="Override eval provider for this run only (claude or langchain)")
    apply_parser.add_argument("--eval-model", type=str, default=None, metavar="MODEL", help="Override eval model for this run only")
    apply_parser.add_argument("--no-save", dest="no_save", action="store_true", help="Run without saving/overwriting the last URL")

    test_parser = subparsers.add_parser("test-apply", help="Test Easy Apply on a specific job URL (skips evaluation)")
    test_parser.add_argument("job_url", type=str, help="LinkedIn job URL (e.g. https://www.linkedin.com/jobs/view/1234567890)")
    test_parser.add_argument("--resume", type=str, default=None, help="Path to resume file (default: resume.txt)")

    bot_parser = subparsers.add_parser("bot", help="Start Telegram bot to control JobPilot remotely")
    bot_parser.add_argument("--resume", type=str, default="resume.txt", help="Path to resume file (default: resume.txt)")

    skills_parser = subparsers.add_parser("skills", help="View missing skills detected during job evaluation")
    skills_sub = skills_parser.add_subparsers(dest="skills_action", required=True)

    skills_list = skills_sub.add_parser("list", help="List all missing skills sorted by frequency")
    skills_list.add_argument("--category", choices=["python", "node", "frontend", "devops", "data", "general"], default=None, help="Filter by category")
    skills_list.add_argument("--level", type=int, choices=[1, 2, 3, 4, 5], default=None, help="Filter by learning level (1=fast, 5=slow)")

    skills_top = skills_sub.add_parser("top", help="Show top most demanded missing skills")
    skills_top.add_argument("--n", type=int, default=10, help="Number of skills to show (default: 10)")
    skills_top.add_argument("--category", choices=["python", "node", "frontend", "devops", "data", "general"], default=None, help="Filter by category")

    skills_sub.add_parser("clear", help="Clear all tracked skills")

    answers_parser = subparsers.add_parser("answers", help="Manage cached form answers (files/qa.json)")
    answers_sub = answers_parser.add_subparsers(dest="answers_action", required=True)

    answers_sub.add_parser("list", help="Show questions with missing answers (numbered)")
    answers_sub.add_parser("show", help="Show all cached answers (numbered)")
    answers_sub.add_parser("fill", help="Interactively answer all missing questions one by one")

    answers_set = answers_sub.add_parser("set", help="Set an answer by question number (from list/show)")
    answers_set.add_argument("number", type=int, help="Question number shown in 'answers list' or 'answers show'")
    answers_set.add_argument("answer", type=str, help="Answer to save")

    answers_sub.add_parser("clear", help="Remove all cached answers")

    report_parser = subparsers.add_parser("report", help="Generate and print monthly report (default: current month)")
    report_parser.add_argument("--month", type=str, default=None, metavar="YYYY-MM", help="Specific month (e.g. 2025-03)")
    report_parser.add_argument("--prev", action="store_true", help="Report for the previous month")
    report_parser.add_argument("--year", type=int, default=None, metavar="YYYY", help="Annual summary for the given year (e.g. 2026)")
    report_parser.add_argument("--telegram", action="store_true", help="Send report via Telegram in addition to printing")
    report_parser.add_argument("--scheduled", action="store_true", help="Scheduled mode: send via Telegram only once per month, skip if already sent")

    provider_parser = subparsers.add_parser("provider", help="Show or change LLM provider settings")
    provider_sub = provider_parser.add_subparsers(dest="provider_action", required=True)

    provider_sub.add_parser("show", help="Show current provider configuration")

    set_parser = provider_sub.add_parser("set", help="Set a provider (claude or langchain)")
    set_parser.add_argument("target", choices=["llm", "eval"], help="Which provider to change: 'llm' (form Q&A) or 'eval' (job evaluation)")
    set_parser.add_argument("backend", choices=["claude", "langchain"], help="Backend to use")
    set_parser.add_argument("--model", type=str, default=None, help="Model name (e.g. claude-haiku-4-5-20251001 or llama3.1:8b)")

    return parser.parse_args()


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
    """Returns (original_question, answer, options_str) for display."""
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
    """Return all entries as an ordered list of (key, entry)."""
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
    print(f'\nUse: answers set <number> "your answer"')


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
        print(f'\nUse: answers set <number> "your answer"')


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
        print(f"     Saved.\n")


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
        # Navigate to the site so cookies are accessible
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


def main():
    args = parse_args()

    if args.task == "skills":
        if args.skills_action == "list":
            run_skills_list(getattr(args, "category", None), getattr(args, "level", None))
        elif args.skills_action == "top":
            run_skills_top(args.n, getattr(args, "category", None))
        elif args.skills_action == "clear":
            run_skills_clear()
        return

    if args.task == "answers":
        if args.answers_action == "list":
            run_answers_list()
        elif args.answers_action == "show":
            run_answers_show()
        elif args.answers_action == "set":
            run_answers_set(args.number, args.answer)
        elif args.answers_action == "fill":
            run_answers_fill()
        elif args.answers_action == "clear":
            run_answers_clear()
        return

    if args.task == "provider":
        if args.provider_action == "show":
            run_provider_show()
        elif args.provider_action == "set":
            run_provider_set(args.target, args.backend, args.model)
        return

    if args.task == "login":
        run_login(args.site)
        return

    if args.task == "logout":
        run_logout(args.site)
        return

    if args.task == "test-apply":
        from src.core.use_cases.job_application_handler import JobApplicationHandler
        from pathlib import Path as _Path
        resume_path = args.resume or "resume.txt"
        _rp = _Path(resume_path)
        if _rp.suffix.lower() == ".pdf":
            from pypdf import PdfReader as _PdfReader
            resume_text = "\n".join(p.extract_text() or "" for p in _PdfReader(resume_path).pages)
        else:
            resume_text = _rp.read_text(encoding="utf-8")
        driver = setup(force_headless=False)
        try:
            driver.get(args.job_url)
            time.sleep(3)
            from src.automation.pages.jobs_search_page import JobsSearchPage
            page = JobsSearchPage(driver, args.job_url)
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
            success = handler.submit_easy_apply(job_title=title, job_description=description)
            print(f"Result: {'SUCCESS' if success else 'FAILED'}")
        finally:
            try:
                input("Press Enter to close browser...")
            except EOFError:
                pass
            driver.quit()
        return

    if args.task == "bot":
        from src.bot.telegram_bot import TelegramBot
        TelegramBot(driver_factory=setup, resume_path=args.resume).run()
        return

    if args.task == "report":
        import sys
        from datetime import date as _date
        from src.core.use_cases.monthly_report import (
            generate_report, generate_year_report, _save_report,
            _format_report, _format_year_report, _prev_month,
            run_monthly_report_scheduled,
        )

        def _print(text: str):
            sys.stdout.buffer.write((text.replace("<b>", "").replace("</b>", "") + "\n").encode("utf-8", "replace"))

        if getattr(args, "scheduled", False):
            run_monthly_report_scheduled()
        elif getattr(args, "year", None):
            report = generate_year_report(args.year)
            _save_report(report)
            if getattr(args, "telegram", False):
                from src.utils.telegram import send_telegram
                send_telegram(_format_year_report(report))
            _print(_format_year_report(report))
        else:
            today = _date.today()
            if getattr(args, "prev", False):
                year, month = _prev_month(today)
            elif getattr(args, "month", None):
                try:
                    year, month = map(int, args.month.split("-"))
                except ValueError:
                    print("Invalid --month format. Use YYYY-MM")
                    return
            else:
                year, month = today.year, today.month
            report = generate_report(year, month)
            _save_report(report)
            if getattr(args, "telegram", False):
                from src.utils.telegram import send_telegram
                send_telegram(_format_report(report))
            _print(_format_report(report))
        return

    last_urls = load_last_urls()

    # Resolve the save key: apply uses per-site keys (apply_linkedin, apply_glassdoor, apply_indeed)
    url = getattr(args, "url", None)
    if args.task == "apply":
        if url:
            site_key = f"apply_{_detect_site(url)}"
        else:
            explicit_site = getattr(args, "site", None)
            if explicit_site:
                site_key = f"apply_{explicit_site}"
            else:
                site_key = f"apply_{last_urls.get('apply_last_site', 'linkedin')}"
    else:
        site_key = args.task

    saved = last_urls.get(site_key, {})
    if isinstance(saved, str):
        saved = {"url": saved, "page": 1}

    start_page = args.start_page if hasattr(args, "start_page") and args.start_page is not None else 1
    resume_from = getattr(args, "resume_from", False) or getattr(args, "resume", False)

    # apply-specific persisted options — CLI args take priority, then saved, then global default
    level       = getattr(args, "level", [])       or saved.get("level", [])
    preferences = getattr(args, "preferences", "") or saved.get("preferences", "")
    resume_path = (getattr(args, "resume", None)
                   or saved.get("resume")
                   or last_urls.get("default_resume")
                   or "resume.txt")
    llm_prov    = getattr(args, "llm_provider", None)  or saved.get("llm_provider")
    llm_mod     = getattr(args, "llm_model", None)     or saved.get("llm_model")
    eval_prov   = getattr(args, "eval_provider", None) or saved.get("eval_provider")
    eval_mod    = getattr(args, "eval_model", None)    or saved.get("eval_model")

    if args.task == "apply":
        import asyncio
        # Apply per-run provider overrides (do not persist to .env) — CLI > saved > .env
        if llm_prov:
            os.environ["LLM_PROVIDER"] = llm_prov
            logger.info(f"[override] LLM_PROVIDER={llm_prov}")
        if llm_mod:
            key = "LANGCHAIN_MODEL" if os.environ.get("LLM_PROVIDER") == "langchain" else "CLAUDE_MODEL"
            os.environ[key] = llm_mod
            logger.info(f"[override] {key}={llm_mod}")
        if eval_prov:
            os.environ["LLM_PROVIDER_EVAL"] = eval_prov
            logger.info(f"[override] LLM_PROVIDER_EVAL={eval_prov}")
        if eval_mod:
            key = "LANGCHAIN_MODEL_EVAL" if os.environ.get("LLM_PROVIDER_EVAL") == "langchain" else "CLAUDE_MODEL"
            os.environ[key] = eval_mod
            logger.info(f"[override] {key}={eval_mod}")

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

    no_save = getattr(args, "no_save", False)

    if url:
        extra = {}
        if args.task == "apply":
            extra = {
                "level": level, "preferences": preferences, "resume": resume_path,
                "llm_provider": llm_prov, "llm_model": llm_mod,
                "eval_provider": eval_prov, "eval_model": eval_mod,
            }
        if not no_save:
            save_last_url(site_key, url, page=1, extra=extra or None)
            if args.task == "apply":
                data = load_last_urls()
                data["apply_last_site"] = _detect_site(url)
                if getattr(args, "resume", None):
                    data["default_resume"] = args.resume
                with open(LAST_URLS_FILE, "w") as f:
                    json.dump(data, f, indent=2)
    else:
        url = saved.get("url")
        if not url:
            site_hint = f"--site {site_key.replace('apply_', '')} " if args.task == "apply" else ""
            print(f"Error: --url is required for the first '{args.task}' run (no saved URL found for {site_key}).")
            return
        if resume_from:
            start_page = saved.get("page", 1)
            print(f"Resuming '{site_key}' from page {start_page}: {url}")
        else:
            print(f"Using last saved URL for '{site_key}': {url}")
        if args.task == "apply":
            if level:
                print(f"Level filter: {level}")
            if preferences:
                print(f"Preferences: {preferences}")
            if eval_prov:
                print(f"Eval provider: {eval_prov}" + (f" model={eval_mod}" if eval_mod else ""))

    if args.task == "connect" and getattr(args, "scheduled", False):
        if is_already_ran_today():
            logger.info("Already ran today. Skipping.")
            return
        if is_weekly_limit_reached():
            logger.info("Weekly connection limit already reached this week. Skipping.")
            return
        save_ran_today()

    def on_page_change(page: int):
        if no_save:
            return
        extra = None
        if args.task == "apply":
            extra = {
                "level": level, "preferences": preferences, "resume": resume_path,
                "llm_provider": llm_prov, "llm_model": llm_mod,
                "eval_provider": eval_prov, "eval_model": eval_mod,
            }
        save_last_url(site_key, url, page=page, extra=extra)

    driver = setup(force_headless=getattr(args, "headless", False))
    try:
        if args.task == "connect":
            from src.core.use_cases.monthly_report import save_connections
            manager = ConnectionManager(driver, url=url, max_pages=args.max_pages, start_page=start_page, on_page_change=on_page_change)
            manager.run()
            sent = manager.connect_people.invite_sended
            if sent:
                save_connections(sent)
            if manager.connect_people.limit_reached:
                save_weekly_limit_reached()
                logger.info("Weekly limit reached — saved. Will skip until next week.")
        elif args.task == "apply":
            JobApplicationManager(driver, url=url, resume_path=resume_path, preferences=preferences, level=level, max_pages=args.max_pages, max_applications=getattr(args, "max_applications", 0), start_page=start_page, on_page_change=on_page_change).run()
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


if __name__ == "__main__":
    load_dotenv()
    main()
