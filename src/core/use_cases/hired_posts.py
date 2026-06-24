"""Parsing puro de posts de anúncio de contratação (feature `hired`).

Funções stateless/testáveis usadas pelo manager p/ filtrar quais posts do
content-search são contratações recentes do cargo-alvo. Lógica validada no
spike (`scripts/spike_hired.py`): a data relativa do post = recência.
"""

import re

# Idade relativa do post (PT/EN) → dias aproximados. "3 d", "2 sem", "1 mês".
_AGE_RE = re.compile(
    r"\b(\d{1,2})\s*(d|dias?|sem(?:ana)?s?|m[eê]s(?:es)?|h|min|w|mo|months?|weeks?|days?)\b",
    re.IGNORECASE,
)

# Frase que caracteriza anúncio de contratação/novo cargo.
_ANNOUNCE_RE = re.compile(
    r"comecei como|nova posi[çc]|orgulho.{0,20}anunciar|"
    r"estou (?:muito )?(?:feliz|animado|entusiasmado|honrado).{0,40}(?:anunciar|compartilhar)|"
    r"started (a )?(new )?(position|role|job)|i('| a)m (happy|excited|thrilled|proud).{0,40}(join|start|announc)|"
    r"\bjoined\b.{0,30}(as|team)|new role|new position",
    re.IGNORECASE,
)

# Sinais de busca de emprego — exclui posts de quem QUER emprego, não anunciou.
_SEEKING_RE = re.compile(
    r"buscando.{0,30}(?:novo cargo|nova oportunidade|emprego|vaga)|"
    r"em busca.{0,30}(?:novo cargo|nova oportunidade|emprego|vaga)|"
    r"aberto a novas oportunidades|open to work|open to opportunities|"
    r"disponível para.{0,20}(?:novo|oportunidade)|"
    r"procurando.{0,30}(?:vaga|emprego|oportunidade)|"
    r"alguém.{0,30}(?:vaga|oportunidade)|"
    r"me indica|me indicar|indicação",
    re.IGNORECASE,
)


def post_age_days(text: str) -> int | None:
    """Idade do post em dias a partir do token relativo. None se ausente.

    Horas/minutos contam como 0 (postado hoje). Semana=7, mês=30.
    """
    match = _AGE_RE.search(text or "")
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2).lower()
    if unit.startswith(("h", "min")):
        return 0
    if unit.startswith("d"):
        return amount
    if unit.startswith(("sem", "w", "week")):
        return amount * 7
    if unit.startswith(("mês", "mes", "mo", "month")):
        return amount * 30
    return None


def is_hire_announcement(text: str) -> bool:
    t = text or ""
    if _SEEKING_RE.search(t):
        return False
    return bool(_ANNOUNCE_RE.search(t))


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^\wÀ-ÿ]+", (value or "").lower())
        if len(token) > 2
    }


def matches_role(text: str, headline: str, role: str) -> bool:
    """True se alguma palavra significativa do cargo-alvo aparece no post/headline."""
    role_tokens = _tokens(role)
    if not role_tokens:
        return True
    candidate_tokens = _tokens(text) | _tokens(headline)
    return bool(role_tokens & candidate_tokens)
