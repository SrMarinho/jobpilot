from urllib.parse import urlencode


def _linkedin_date_posted_value(value: str) -> str | None:
    mapping = {"24h": "r86400", "week": "r604800", "month": "r2592000"}
    return mapping.get(value)


def _linkedin_workplace_value(value: str) -> str | None:
    mapping = {"on-site": "1", "remote": "2", "hybrid": "3"}
    return mapping.get(value)


def _linkedin_experience_value(value: str) -> str | None:
    mapping = {
        "internship": "1",
        "entry": "2",
        "associate": "3",
        "mid-senior": "4",
        "director": "5",
        "executive": "6",
    }
    return mapping.get(value)


def _indeed_date_posted_value(value: str) -> str | None:
    mapping = {"24h": "1", "3d": "3", "week": "7", "14d": "14"}
    return mapping.get(value)


def build_linkedin_jobs_url(
    keywords: list[str],
    date_posted: str | None = None,
    workplace: str | None = None,
    location: str | None = None,
    experience: str | None = None,
    easy_apply_only: bool = False,
) -> str:
    params = {"keywords": " ".join(keywords)}
    if easy_apply_only:
        params["f_AL"] = "true"
    dp = _linkedin_date_posted_value(date_posted) if date_posted else None
    if dp:
        params["f_TPR"] = dp
    wp = _linkedin_workplace_value(workplace) if workplace else None
    if wp:
        params["f_WT"] = wp
    if location:
        params["location"] = location
    xp = _linkedin_experience_value(experience) if experience else None
    if xp:
        params["f_E"] = xp
    return f"https://www.linkedin.com/jobs/search/?{urlencode(params)}"


def build_linkedin_people_url(keywords: list[str], network: str | None = None) -> str:
    params = {"keywords": " ".join(keywords)}
    if network:
        params["network"] = f'["{network}"]'
    return f"https://www.linkedin.com/search/results/people/?{urlencode(params)}"


def build_linkedin_hired_posts_url(
    role: str, extra_terms: list[str] | None = None
) -> str:
    """Busca de POSTS de anúncio de contratação recente, ordenados por data.

    A data do post ≈ data da contratação → recência grátis (sem abrir perfil).
    Validado no spike: 6 anúncios reais no 1º goto, sem checkpoint.
    """
    announce = '"comecei como" OR "started a new position" OR "novo cargo"'
    terms = [f"({announce})", role]
    if extra_terms:
        terms.extend(extra_terms)
    params = {"keywords": " ".join(terms), "sortBy": '"date_posted"'}
    return f"https://www.linkedin.com/search/results/content/?{urlencode(params)}"


def build_indeed_url(
    keywords: list[str],
    date_posted: str | None = None,
    location: str | None = None,
) -> str:
    params = {"q": " ".join(keywords), "sc": "0kf:attr(DSK7o)jt(fc)"}
    if location:
        params["l"] = location
    dp = _indeed_date_posted_value(date_posted) if date_posted else None
    if dp:
        params["fromage"] = dp
    return f"https://br.indeed.com/jobs?{urlencode(params)}"
