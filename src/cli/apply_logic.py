import typer

from src.automation.tasks.job_application_manager import _detect_site
from src.automation import url_builder as _url_builder
from src.cli.persistence import load_last_urls, _find_resume


def _determine_site_key(
    url: str | None,
    keywords: str | None,
    site_name: str | None,
) -> str:
    last_urls = load_last_urls()
    if url:
        return f"apply_{_detect_site(url)}"
    if site_name:
        return f"apply_{site_name}"
    return f"apply_{last_urls.get('apply_last_site', 'linkedin')}"


def _resolve_apply_url_task(
    url: str | None,
    keywords: str | None,
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
    resume_from: bool,
    site_name: str | None,
    resume_path_arg: str | None,
) -> tuple[str, int, str, str, dict]:
    last_urls = load_last_urls()
    site_key = _determine_site_key(url, keywords, site_name)
    target_site = site_key.replace("apply_", "")

    saved: dict = last_urls.get(site_key, {})
    if isinstance(saved, str):
        saved = {"url": saved, "page": 1}

    search_params: dict = {}

    if url:
        resolved_url = url
        start_page = 1
        search_params = {}
    elif keywords:
        resolved_url = _build_search_url(target_site, keywords, date_posted, workplace, location, experience)
        start_page = 1
        search_params = {
            "keywords": keywords, "date_posted": date_posted,
            "workplace": workplace, "location": location, "experience": experience,
        }
        print(f"Using search: keywords='{keywords}'" + (f", date_posted={date_posted}" if date_posted else "") + (f", workplace={workplace}" if workplace else ""))
    else:
        saved_keywords = saved.get("keywords")
        if saved_keywords:
            resolved_url = _build_search_url(
                target_site,
                saved_keywords,
                saved.get("date_posted"),
                saved.get("workplace"),
                saved.get("location"),
                saved.get("experience"),
            )
            search_params = {
                "keywords": saved_keywords,
                "date_posted": saved.get("date_posted"),
                "workplace": saved.get("workplace"),
                "location": saved.get("location"),
                "experience": saved.get("experience"),
            }
        else:
            resolved_url = saved.get("url") if isinstance(saved, dict) else None
            if not resolved_url:
                print(f"Error: --url or --keywords is required for the first 'apply' run on {site_key}.")
                raise typer.Exit()
            search_params = {}

        if resume_from:
            start_page = saved.get("page", 1)
            print(f"Resuming '{site_key}' from page {start_page}: {resolved_url}")
        else:
            start_page = 1
            print(f"Using last saved search for '{site_key}': {resolved_url}")

    resolved_resume: str = (
        resume_path_arg
        or (saved.get("resume") if isinstance(saved, dict) else None)
        or last_urls.get("default_resume")
        or _find_resume()
    )

    return resolved_url, start_page, site_key, resolved_resume, search_params


def _build_search_url(
    site: str,
    keywords: str,
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
) -> str:
    if site == "indeed":
        return _url_builder.build_indeed_url(keywords, date_posted=date_posted, location=location)
    return _url_builder.build_linkedin_jobs_url(
        keywords, date_posted=date_posted, workplace=workplace,
        location=location, experience=experience,
    )


def _resolve_saved_options(saved: dict) -> tuple[list[str], str, str | None, str | None, str | None, str | None]:
    level: list[str] = saved.get("level", []) if isinstance(saved, dict) else []
    preferences: str = saved.get("preferences", "") if isinstance(saved, dict) else ""
    llm_prov = saved.get("llm_provider") if isinstance(saved, dict) else None
    llm_mod = saved.get("llm_model") if isinstance(saved, dict) else None
    eval_prov = saved.get("eval_provider") if isinstance(saved, dict) else None
    eval_mod = saved.get("eval_model") if isinstance(saved, dict) else None
    return level, preferences, llm_prov, llm_mod, eval_prov, eval_mod


def _search_params_dict(
    keywords: str | None, date_posted: str | None,
    workplace: str | None, location: str | None, experience: str | None,
) -> dict:
    return {
        "keywords": keywords, "date_posted": date_posted,
        "workplace": workplace, "location": location, "experience": experience,
    }
