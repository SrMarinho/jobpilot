from src.automation.tasks.base_application_manager import (
    BaseJobApplicationManager,
    detect_level as _detect_level,
)
from src.automation.tasks.linkedin_application_manager import (
    LinkedInJobApplicationManager,
)
from src.automation.tasks.indeed_application_manager import IndeedJobApplicationManager
from src.automation.tasks.glassdoor_application_manager import (
    GlassdoorJobApplicationManager,
)


def _detect_site(url: str) -> str:
    if "indeed.com" in url:
        return "indeed"
    if "glassdoor.com" in url:
        return "glassdoor"
    return "linkedin"


_MANAGERS = {
    "linkedin": LinkedInJobApplicationManager,
    "indeed": IndeedJobApplicationManager,
    "glassdoor": GlassdoorJobApplicationManager,
}


def create_application_manager(
    page, url: str, *args, **kwargs
) -> BaseJobApplicationManager:
    """Factory — picks subclass by URL host."""
    cls = _MANAGERS[_detect_site(url)]
    return cls(page, url, *args, **kwargs)


__all__ = [
    "create_application_manager",
    "BaseJobApplicationManager",
    "LinkedInJobApplicationManager",
    "IndeedJobApplicationManager",
    "GlassdoorJobApplicationManager",
    "_detect_site",
    "_detect_level",
]
