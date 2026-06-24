"""Filtros de qualidade do COMENTÁRIO gerado pela LLM (saída).

Separado de ``content_filters`` (que decide se vale engajar o POST). Aqui só se
o comentário já gerado presta: ancoragem, cliché, tom iniciante/junior, stack
alucinado e validação estrutural. Reusa utils de texto do ``content_filters``.
"""

import re

from src.core.use_cases.content_filters import content_tokens


def comment_is_grounded(comment: str, post_text: str) -> bool:
    """True se o comentário referencia algo que o post realmente diz.

    Compara palavras-conteúdo por prefixo (5 chars) p/ tolerar flexão. Zero
    overlap => comentário ungrounded (provável alucinação), rejeita.
    """
    c_tokens = content_tokens(comment)
    if not c_tokens:
        return False
    p_prefixes = {w[:5] for w in content_tokens(post_text)}
    return any(w[:5] in p_prefixes for w in c_tokens)


_CLICHE_PATTERNS = (
    r"^(ótimo|otimo|excelente|incrível|incrivel|amazing|great|awesome) post[!.]?\s*$",
    r"^(concordo|i agree|agreed)[!.]?\s*$",
    r"^muito bom[!.]?\s*$",
    r"^perfect[oa]?[!.]?\s*$",
    r"^\W*$",
)
_CLICHE_RE = re.compile("|".join(_CLICHE_PATTERNS), re.IGNORECASE)


def is_cliche(comment: str) -> bool:
    """True p/ resposta vazia de baixo esforço ('ótimo post!', 'concordo')."""
    return bool(_CLICHE_RE.match(comment.strip()))


# Recusa/meta: às vezes o modelo, em vez de devolver string vazia, EXPLICA por
# que não vai comentar ("não há conteúdo técnico", "retornar string vazia"). Não
# é um comentário — tratar como vazio direto, sem gastar retry nem postar.
_REFUSAL_PATTERNS = (
    r"string vazia",
    r"retorn\w* vazi",
    r"n[ãa]o h[áa] (pergunta|conte[úu]do|stack|contexto|substância|informaç)",
    r"puramente promocional",
    r"sem (conte[úu]do|substância) (t[ée]cnic|espec[íi]fic)",
    r"n[ãa]o (vou |há o que |dá para |posso )?comentar",
    r"n[ãa]o (é poss[íi]vel|permite) comentar",
)
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), re.IGNORECASE)


def is_refusal(comment: str) -> bool:
    """True se o texto é o modelo explicando que NÃO vai comentar (≈ vazio)."""
    return bool(_REFUSAL_RE.search(comment or ""))


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


# Tom junior: marcadores de aprendiz, entusiasmo vazio ou pedido de ajuda. Não
# passa credibilidade de sênior — distinto de is_trivial (que pega perguntas
# básicas "o que é X?"). Aqui pega "estou aprendendo", "boa dica", "salvando".
_JUNIOR_TONE_PATTERNS = (
    r"\b(estou|to|tô) (aprendendo|estudando|começando|comecando)\b",
    r"\bvou (estudar|testar|aprender|tentar|ver isso|olhar isso)\b",
    r"\b(salvando|salvei|guardando) (para|pra|pro) depois\b",
    r"\balguém (pode |poderia )?(explica|explicar|ajuda|ajudar)\b",
    r"\b(boa|ótima|otima|excelente) (dica|dicas|ideia|sacada)\b",
    r"\b(sou|ainda sou|como) (iniciante|junior|júnior)\b",
    r"\bcomecei (agora|há pouco|ha pouco)\b",
    r"\bpreciso (aprender|estudar) (mais |)isso\b",
    r"\bi'?m (learning|new to|starting)\b",
    r"\b(saving|bookmarking) (this )?for later\b",
    r"\bcan (someone|anyone) explain\b",
    r"\bgreat (tip|tips|advice)\b",
)
_JUNIOR_TONE_RE = re.compile("|".join(_JUNIOR_TONE_PATTERNS), re.IGNORECASE)


def is_junior_tone(comment: str) -> bool:
    """True p/ marcadores de tom junior (aprendiz/entusiasmo vazio/pedido de ajuda)."""
    return bool(_JUNIOR_TONE_RE.search(comment))


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


def validate_comment(
    comment: str,
    min_words: int = 5,
    max_words: int = 40,
    max_chars: int = 320,
) -> tuple[bool, str]:
    comment = (comment or "").strip().strip('"').strip("'")
    if not comment:
        return False, "empty"
    words = comment.split()
    if len(words) < min_words:
        return False, f"too short ({len(words)} words)"
    if len(words) > max_words:
        return False, f"too long ({len(words)} words)"
    if len(comment) > max_chars:
        return False, f"too long ({len(comment)} chars)"
    if is_cliche(comment):
        return False, "cliche"
    if "emoji" in comment.lower():
        return False, "mentions emoji"
    if re.search(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", comment):
        return False, "contains emoji"
    return True, comment
