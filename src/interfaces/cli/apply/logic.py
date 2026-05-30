import typer

from src.automation.tasks.job_application_manager import _detect_site
from src.automation import url_builder as _url_builder
from src.interfaces.cli.persistence import load_last_urls, save_last_url, _find_resume


def _determine_site_key(
    url: str | None,
    keywords: list[str] | None,
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
    keywords: list[str] | None,
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
    resume_from: bool,
    site_name: str | None,
    resume_path_arg: str | None,
    all_types: bool = True,
) -> tuple[str, int, str, str, dict]:
    last_urls = load_last_urls()
    site_key = _determine_site_key(url, keywords, site_name)
    target_site = site_key.replace("apply_", "")

    saved: dict = last_urls.get(site_key, {})
    if isinstance(saved, str):
        saved = {"url": saved, "page": 1}

    search_params: dict = {}

    if url:
        # Raw URL mode: use the provided URL
        resolved_url = url
        start_page = 1
        search_params = {}  # no search params in raw URL mode
    elif keywords:
        # Search builder mode with newly provided keywords
        resolved_url = _build_search_url(
            target_site,
            keywords,
            date_posted,
            workplace,
            location,
            experience,
            all_types=all_types,
        )
        start_page = 1
        search_params = {
            "keywords": " ".join(keywords),
            "date_posted": date_posted,
            "workplace": workplace,
            "location": location,
            "experience": experience,
        }
        print(
            f"Using search: keywords='{' '.join(keywords)}'"
            + (f", date_posted={date_posted}" if date_posted else "")
            + (f", workplace={workplace}" if workplace else "")
            + (" [Easy Apply only]" if not all_types else "")
        )
    else:
        # Load from saved config
        saved_keywords_raw = saved.get("keywords")
        saved_keywords: list[str] | None = None
        if saved_keywords_raw:
            if isinstance(saved_keywords_raw, str):
                saved_keywords = saved_keywords_raw.split()
            else:
                saved_keywords = saved_keywords_raw
        if saved_keywords:
            # Rebuild URL from saved search params
            resolved_url = _build_search_url(
                target_site,
                saved_keywords,
                saved.get("date_posted"),
                saved.get("workplace"),
                saved.get("location"),
                saved.get("experience"),
                all_types=all_types,
            )
            search_params = {
                "keywords": saved_keywords,
                "date_posted": saved.get("date_posted"),
                "workplace": saved.get("workplace"),
                "location": saved.get("location"),
                "experience": saved.get("experience"),
            }
        else:
            # Legacy: raw URL saved
            resolved_url = saved.get("url") if isinstance(saved, dict) else None
            if not resolved_url:
                print(
                    f"Error: --url or --keywords is required for the first 'apply' run on {site_key}."
                )
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
    keywords: list[str],
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
    all_types: bool = True,
) -> str:
    if site == "indeed":
        return _url_builder.build_indeed_url(
            keywords, date_posted=date_posted, location=location
        )
    return _url_builder.build_linkedin_jobs_url(
        keywords,
        date_posted=date_posted,
        workplace=workplace,
        location=location,
        experience=experience,
        easy_apply_only=not all_types,
    )


def _resolve_saved_options(
    saved: dict,
) -> tuple[list[str], str, str | None, str | None, str | None, str | None]:
    level: list[str] = saved.get("level", []) if isinstance(saved, dict) else []
    preferences: str = saved.get("preferences", "") if isinstance(saved, dict) else ""
    llm_prov = saved.get("llm_provider") if isinstance(saved, dict) else None
    llm_mod = saved.get("llm_model") if isinstance(saved, dict) else None
    eval_prov = saved.get("eval_provider") if isinstance(saved, dict) else None
    eval_mod = saved.get("eval_model") if isinstance(saved, dict) else None
    return level, preferences, llm_prov, llm_mod, eval_prov, eval_mod


def _search_params_dict(
    keywords: list[str] | None,
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
) -> dict:
    return {
        "keywords": " ".join(keywords) if keywords else None,
        "date_posted": date_posted,
        "workplace": workplace,
        "location": location,
        "experience": experience,
    }


def prepare_apply_config(
    url: str | None,
    keywords: list[str] | None,
    date_posted: str | None,
    workplace: str | None,
    location: str | None,
    experience: str | None,
    resume: str | None,
    preferences: str | None,
    level: list[str] | None,
    site_name: str | None,
    resume_from: bool,
    llm_provider: str | None,
    llm_model: str | None,
    eval_provider: str | None,
    eval_model: str | None,
    no_save: bool,
    easy_apply_only: bool,
) -> dict:
    """Resolve URL, merge config, warmup LLM, save state.

    Returns a dict with keys: url, start_page, site_key, resume_path,
    level, preferences, on_page_change.
    """
    import json
    from src.interfaces.cli.persistence import LAST_URLS_FILE

    # ── URL resolution ──
    if not url and not keywords:
        site_key_check = _determine_site_key(None, None, site_name)
        saved_check = load_last_urls().get(site_key_check, {})
        if not saved_check.get("url") and not saved_check.get("keywords"):
            print("Error: pass --url or --keywords for the first run.")
            raise typer.Exit()

    resolved_url, resolved_start_page, site_key, resolved_resume, resolved_search = (
        _resolve_apply_url_task(
            url,
            keywords,
            date_posted,
            workplace,
            location,
            experience,
            resume_from,
            site_name,
            resume,
            all_types=not easy_apply_only,
        )
    )

    # ── merge CLI args > saved ──
    saved = load_last_urls().get(site_key, {})
    final_level = level or _resolve_saved_options(saved)[0] or []
    final_preferences = preferences or _resolve_saved_options(saved)[1] or ""
    final_llm_prov = llm_provider or _resolve_saved_options(saved)[2]
    final_llm_mod = llm_model or _resolve_saved_options(saved)[3]
    final_eval_prov = eval_provider or _resolve_saved_options(saved)[4]
    final_eval_mod = eval_model or _resolve_saved_options(saved)[5]

    final_search = resolved_search.copy()
    if keywords:
        final_search["keywords"] = " ".join(keywords)
    if date_posted:
        final_search["date_posted"] = date_posted
    if workplace:
        final_search["workplace"] = workplace
    if location:
        final_search["location"] = location
    if experience:
        final_search["experience"] = experience

    if final_level:
        print(f"Level filter: {final_level}")
    if final_preferences:
        print(f"Preferences: {final_preferences}")
    if final_eval_prov:
        print(
            f"Eval provider: {final_eval_prov}"
            + (f" model={final_eval_mod}" if final_eval_mod else "")
        )

    # ── LLM setup ──
    from src.core.ai.warmup import apply_provider_overrides, warmup_llm_providers

    apply_provider_overrides(
        final_llm_prov, final_llm_mod, final_eval_prov, final_eval_mod
    )
    warmup_llm_providers()

    # ── save config ──
    if not no_save:
        extra = {
            "level": final_level,
            "preferences": final_preferences,
            "resume": resolved_resume,
            "llm_provider": final_llm_prov,
            "llm_model": final_llm_mod,
            "eval_provider": final_eval_prov,
            "eval_model": final_eval_mod,
        }
        extra.update(final_search)
        if keywords or url:
            save_last_url(site_key, resolved_url, page=1, extra=extra)
            data = load_last_urls()
            if url:
                data["apply_last_site"] = _detect_site(url)
            else:
                data["apply_last_site"] = site_key.replace("apply_", "")
            if resume:
                data["default_resume"] = resume
            with open(LAST_URLS_FILE, "w") as f:
                json.dump(data, f, indent=2)

    # ── on_page_change callback ──
    def on_page_change(page: int):
        if no_save:
            return
        extra = {
            "level": final_level,
            "preferences": final_preferences,
            "resume": resolved_resume,
            "llm_provider": final_llm_prov,
            "llm_model": final_llm_mod,
            "eval_provider": final_eval_prov,
            "eval_model": final_eval_mod,
        }
        extra.update(final_search)
        save_last_url(site_key, resolved_url, page=page, extra=extra)

    return {
        "url": resolved_url,
        "start_page": resolved_start_page,
        "site_key": site_key,
        "resume_path": resolved_resume,
        "level": final_level,
        "preferences": final_preferences,
        "on_page_change": on_page_change,
    }
