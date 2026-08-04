"""Reconhecimento de URL de vaga em texto solto do Telegram.

Deliberadamente estreito: só casa link de *vaga específica* dos boards
suportados. Um link de busca (``/jobs/search``) ou de perfil não é vaga, e
tratar como tal faria a triagem avaliar a página errada e gravar lixo no
histórico.
"""

import re

# Padrões de vaga individual, por board.
_JOB_URL_PATTERNS = (
    r"linkedin\.com/jobs/view/\d+",
    # currentJobId identifica UMA vaga, mesmo dentro da URL de busca.
    r"linkedin\.com/jobs/\S*currentJobId=\d+",
    r"(?:br\.)?indeed\.com/(?:viewjob|rc/clk)\?[^\s]*jk=",
    r"glassdoor\.com(?:\.br)?/job-listing/",
    r"gupy\.io/job[s]?/\d+",
)
_JOB_URL_RE = re.compile("|".join(_JOB_URL_PATTERNS), re.IGNORECASE)


def is_job_url(text: str) -> bool:
    """``True`` se o texto é (ou contém) o link de uma vaga específica."""
    candidate = (text or "").strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return False
    return bool(_JOB_URL_RE.search(candidate))


def extract_job_url(text: str) -> str | None:
    """Primeira URL de vaga encontrada no texto, ou ``None``."""
    for token in (text or "").split():
        if is_job_url(token):
            return token.strip()
    return None
