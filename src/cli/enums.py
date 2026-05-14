from enum import Enum


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


class DatePosted(str, Enum):
    h24 = "24h"
    week = "week"
    month = "month"
    any_ = "any"


class WorkplaceType(str, Enum):
    on_site = "on-site"
    remote = "remote"
    hybrid = "hybrid"


class ExperienceLevel(str, Enum):
    internship = "internship"
    entry = "entry"
    associate = "associate"
    mid_senior = "mid-senior"
    director = "director"
    executive = "executive"


class NetworkDegree(str, Enum):
    first = "F"
    second = "S"
    third = "O"
