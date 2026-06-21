import os
import re


_BLACKLIST_KEYWORDS = {
    "politica",
    "política",
    "eleicao",
    "eleição",
    "religiao",
    "religião",
    "aborto",
    "vacina",
    "racismo",
    "lgbt",
    "bolsonaro",
    "lula",
    "trump",
    "biden",
    "abortion",
    "gun control",
    "vaccine",
    "election",
    "religion",
    "racist",
    "racism",
    "transgender",
    "vagas para",
    "estamos contratando",
    "we are hiring",
    "we're hiring",
    "estamos buscando",
    "recruiter",
    "recrutador",
}

_TECH_KEYWORDS = (
    "python",
    "node",
    "nodejs",
    "javascript",
    "typescript",
    "java",
    "golang",
    " go ",
    "rust",
    "react",
    "vue",
    "angular",
    "django",
    "flask",
    "fastapi",
    "spring",
    "kubernetes",
    "k8s",
    "docker",
    "devops",
    "cloud",
    "aws",
    "azure",
    "gcp",
    "google cloud",
    "terraform",
    "ci/cd",
    "cicd",
    "pipeline",
    "microservi",
    "api",
    "rest",
    "graphql",
    "sql",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "banco de dados",
    "database",
    "backend",
    "frontend",
    "full-stack",
    "fullstack",
    "machine learning",
    "ml",
    " ia ",
    " ai ",
    "inteligência artificial",
    "inteligencia artificial",
    "llm",
    "data",
    "dados",
    "etl",
    "engenharia de software",
    "software",
    "desenvolv",
    "programa",
    "código",
    "codigo",
    "git",
    "linux",
    "observability",
    "monitoring",
    "rpa",
    "automacao",
    "automação",
    "agile",
    "scrum",
    "arquitetura",
    "architecture",
    "deploy",
    "infraestrutura",
    "infra",
    "engineer",
    "developer",
    "tech",
    "ti ",
    "framework",
    "biblioteca",
    "library",
)


_URL_RE = re.compile(
    r"https?://\S+|www\.\S+|lnkd\.in/\S+|\b\S+\.(?:com|io|dev|net|org|br)\S*"
)
_EMOJI_RE = re.compile(
    r"[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF️‍]"
)
# Risada/filler de baixo esforço: "kkkk", "hahaha", "rsrs", "huehue", "ksks".
_LAUGH_RE = re.compile(
    r"\b(?:k{2,}|(?:ha){2,}|(?:he){2,}|(?:rs){2,}|(?:hue){2,}|(?:ks){2,}|haha\w*|kkk\w*)\b",
    re.IGNORECASE,
)


def strip_noise(text: str) -> str:
    """Remove URLs, emojis e risada/filler; colapsa espaços. Sobra o texto 'real'."""
    text = _URL_RE.sub(" ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = _LAUGH_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_tech_keyword(text: str) -> bool:
    # roda sobre texto sem URL: link de github não deve injetar sinal 'git'
    low = f" {strip_noise(text).lower()} "
    return any(kw in low for kw in _TECH_KEYWORDS)


# Palavras-função PT/EN ignoradas no grounding (não ancoram nada).
_STOPWORDS = {
    "para",
    "como",
    "você",
    "voce",
    "este",
    "esta",
    "esse",
    "essa",
    "isso",
    "aqui",
    "muito",
    "mais",
    "menos",
    "sobre",
    "quando",
    "onde",
    "porque",
    "quais",
    "qual",
    "foram",
    "foi",
    "está",
    "esta",
    "estão",
    "ter",
    "tem",
    "uma",
    "uns",
    "umas",
    "com",
    "sem",
    "seu",
    "sua",
    "meu",
    "minha",
    "pelo",
    "pela",
    "nos",
    "nas",
    "que",
    "the",
    "this",
    "that",
    "with",
    "your",
    "from",
    "what",
    "were",
    "have",
    "been",
    "about",
    "interessante",
    "legal",
    "bacana",
    "parabens",
    "parabéns",
}


def _content_tokens(text: str) -> set[str]:
    text = strip_noise(text).lower()
    words = re.findall(r"[a-zà-ÿ0-9]+", text)
    return {w for w in words if len(w) >= 4 and w not in _STOPWORDS}


# Mínimo de palavras na legenda p/ comentar. Legenda grande = mais contexto =
# menos alucinação. Tunável via env (ENGAGE_MIN_CAPTION_WORDS).
_MIN_CAPTION_WORDS = int(os.getenv("ENGAGE_MIN_CAPTION_WORDS", "40"))


def is_commentable_post(text: str) -> bool:
    """Comenta só em post de LEGENDA GRANDE e com termo tech — o bot NÃO vê imagem.

    Legenda curta / dominada por risada / sem tech => contexto insuficiente (o
    conteúdo real está na imagem ou é baixo esforço) => pula, senão o modelo
    inventa. Limiar de palavras tunável via ENGAGE_MIN_CAPTION_WORDS.
    """
    clean = strip_noise(text)
    return len(clean.split()) >= _MIN_CAPTION_WORDS and has_tech_keyword(clean)


def comment_is_grounded(comment: str, post_text: str) -> bool:
    """True se o comentário referencia algo que o post realmente diz.

    Compara palavras-conteúdo por prefixo (5 chars) p/ tolerar flexão. Zero
    overlap => comentário ungrounded (provável alucinação), rejeita.
    """
    c_tokens = _content_tokens(comment)
    if not c_tokens:
        return False
    p_prefixes = {w[:5] for w in _content_tokens(post_text)}
    return any(w[:5] in p_prefixes for w in c_tokens)


_CLICHE_PATTERNS = (
    r"^(ótimo|otimo|excelente|incrível|incrivel|amazing|great|awesome) post[!.]?\s*$",
    r"^(concordo|i agree|agreed)[!.]?\s*$",
    r"^muito bom[!.]?\s*$",
    r"^perfect[oa]?[!.]?\s*$",
    r"^\W*$",
)
_CLICHE_RE = re.compile("|".join(_CLICHE_PATTERNS), re.IGNORECASE)


def is_blacklisted(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _BLACKLIST_KEYWORDS)


def is_cliche(comment: str) -> bool:
    return bool(_CLICHE_RE.match(comment.strip()))


# Comentário trivial/de iniciante: pergunta óbvia ("o que é X?", "como o X
# facilita?", "para que serve?") ou definição do básico. Não passa credibilidade
# de sênior — melhor não comentar.
_TRIVIAL_PATTERNS = (
    r"\bo que (é|e|sao|são)\b",
    r"\bpara que serve\b",
    r"\bcomo (?:o |a |os |as )?\w+ (?:funciona|funcionam|facilita|facilitam|"
    r"ajuda|ajudam|melhora|melhoram|impacta|impactam)\b",
    r"\bqual (?:a |o )?(?:diferença|definição|conceito) (?:de|do|da|entre)\b",
    r"\bwhat (?:is|are)\b",
    r"\bhow (?:do|does)\b.*\bwork\b",
)
_TRIVIAL_RE = re.compile("|".join(_TRIVIAL_PATTERNS), re.IGNORECASE)


def is_trivial(comment: str) -> bool:
    """True p/ pergunta de iniciante / explicação do óbvio."""
    return bool(_TRIVIAL_RE.search(comment))


# Linguagens/frameworks nomeados. Se o comentário cita um que NÃO aparece no
# post, o modelo alucinou o stack (ex: falar de Django num post sobre Spring).
_NAMED_TECH = (
    "python",
    "django",
    "flask",
    "fastapi",
    "java",
    "spring",
    "kotlin",
    "scala",
    "javascript",
    "typescript",
    "node",
    "nodejs",
    "react",
    "vue",
    "angular",
    "svelte",
    "golang",
    "rust",
    "c#",
    ".net",
    "php",
    "laravel",
    "symfony",
    "ruby",
    "rails",
    "elixir",
    "django rest",
    "express",
    "nestjs",
    "c++",
)


def foreign_tech_in_comment(comment: str, post_text: str) -> str | None:
    """Retorna o 1º termo de stack citado no comentário e ausente do post."""
    c = comment.lower()
    p = post_text.lower()
    for tech in _NAMED_TECH:
        # match por palavra p/ evitar substrings espúrias (ex: 'java' em 'javascript')
        pat = rf"(?<![a-z0-9]){re.escape(tech)}(?![a-z0-9])"
        if re.search(pat, c) and tech not in p:
            return tech
    return None


def validate_comment(comment: str) -> tuple[bool, str]:
    comment = (comment or "").strip().strip('"').strip("'")
    if not comment:
        return False, "empty"
    words = comment.split()
    if len(words) < 5:
        return False, f"too short ({len(words)} words)"
    if len(comment) > 200:
        return False, f"too long ({len(comment)} chars)"
    if is_cliche(comment):
        return False, "cliche"
    if "emoji" in comment.lower():
        return False, "mentions emoji"
    if re.search(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", comment):
        return False, "contains emoji"
    return True, comment
