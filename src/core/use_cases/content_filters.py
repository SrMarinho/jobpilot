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


def is_blacklisted(text: str) -> bool:
    """True se o texto cita tema vetado (política/religião/anúncio de vaga)."""
    low = text.lower()
    return any(kw in low for kw in _BLACKLIST_KEYWORDS)


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


def content_tokens(text: str) -> set[str]:
    """Palavras-conteúdo (≥4 chars, sem stopwords/URL/emoji). Base do grounding."""
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
