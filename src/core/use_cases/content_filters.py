import re
from src.config.sections import engage as engage_settings


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


# Cargos/headline que marcam autor da área de software. Filtro barato (sem LLM):
# olha o headline de quem postou e só engaja quem é dev/eng/tech.
_DEV_ROLE_KEYWORDS = (
    "desenvolvedor",
    "desenvolvedora",
    "developer",
    "programador",
    "programadora",
    "programmer",
    "software",
    "engenheiro de software",
    "engenheira de software",
    "software engineer",
    "engenheiro de dados",
    "data engineer",
    "engenheiro de machine learning",
    "ml engineer",
    "machine learning engineer",
    "backend",
    "back-end",
    "frontend",
    "front-end",
    "full stack",
    "full-stack",
    "fullstack",
    "devops",
    "sre",
    "tech lead",
    "engineering manager",
    "arquiteto de software",
    "software architect",
    "cientista de dados",
    "data scientist",
    "qa engineer",
    "mobile developer",
    "ios developer",
    "android developer",
    " dev ",
    ".dev",
    "engineer",
    "cto",
    "founder",
    "co-founder",
    "cofounder",
    "head of engineering",
    "vp of engineering",
    "staff engineer",
    "principal engineer",
    "arquiteto de soluções",
    "solutions architect",
)


def post_asks_question(post_text: str) -> bool:
    """True se o post faz uma pergunta (tem '?' ou interrogativo). Post-pergunta
    é o caso mais fácil de comentar: o autor já pediu uma resposta."""
    t = (post_text or "").strip().lower()
    if "?" in t:
        return True
    return bool(
        re.search(r"\b(qual|quais|como|quando|em qual|o que|por que|porque)\b", t)
    )


def author_is_dev(headline: str) -> bool:
    """True se o headline do autor indica cargo de software/dev. Heurística
    barata (sem LLM) p/ filtrar quem posta fora da área de programação."""
    if not headline:
        return False
    low = f" {headline.lower()} "
    if any(kw in low for kw in _DEV_ROLE_KEYWORDS):
        return True
    # Stack técnico no headline ("CTO @ X | Node.js | Python") também conta.
    return has_tech_keyword(headline)


# Nome próprio: 1-5 palavras capitalizadas ("Daniel Moraes", "NVIDIA Brasil").
_NAME_LINE_RE = re.compile(r"^[A-ZÀ-Ý][\w.'\-]*(\s+[A-ZÀ-Ý][\w.'\-]*){0,4}$")


def headline_is_junk(headline: str, author: str = "") -> bool:
    """True se o 'headline' parseado parece lixo de UI, não um cargo: nome do
    autor repetido, linha de perfil/premium, ou só um nome próprio. Lixo deve
    ser tratado como headline ausente (não bloqueia o filtro de cargo)."""
    h = (headline or "").strip()
    if not h:
        return True
    if author and h.lower() == author.strip().lower():
        return True
    if re.search(r"\bperfil\b|\bpremium\b|\d+º", h.lower()):
        return True
    if "|" not in h and "•" not in h and _NAME_LINE_RE.match(h):
        return True
    return False


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
_MIN_CAPTION_WORDS = engage_settings.min_caption_words


def is_commentable_post(text: str) -> bool:
    """Comenta só em post de LEGENDA GRANDE e com termo tech — o bot NÃO vê imagem.

    Legenda curta / dominada por risada / sem tech => contexto insuficiente (o
    conteúdo real está na imagem ou é baixo esforço) => pula, senão o modelo
    inventa. Limiar de palavras tunável via ENGAGE_MIN_CAPTION_WORDS.
    """
    clean = strip_noise(text)
    return len(clean.split()) >= _MIN_CAPTION_WORDS and has_tech_keyword(clean)
