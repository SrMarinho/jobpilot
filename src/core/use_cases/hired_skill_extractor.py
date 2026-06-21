"""Extração de skills TÉCNICAS de um perfil via LLM (feature `hired`).

O bloco inline "Principais competências" do LinkedIn (1) só aparece em ~40% dos
perfis e (2) mistura ruído (idiomas, termos genéricos como "Desenvolvimento de
software"). O LLM lê o miolo do perfil + as skills inline e devolve só skills
técnicas normalizadas — cobrindo perfis sem o bloco e filtrando o ruído.
"""

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.skills_tracker import _canonical_skill

_MAX_SKILLS = 12

_PROMPT = """Extraia as competências TÉCNICAS deste perfil do LinkedIn de um profissional de tecnologia.

PERFIL:
\"\"\"
{profile_text}
\"\"\"

COMPETÊNCIAS INLINE (dica, pode estar vazia): {inline}

Regras:
- Retorne SÓ skills técnicas: linguagens, frameworks, bibliotecas, bancos de dados, cloud, ferramentas de devops/dados.
- NÃO inclua idiomas (inglês, espanhol), soft skills, nem termos genéricos ("desenvolvimento de software", "programação", "tecnologia da informação", "lógica").
- Normalize nomes (ex: "ReactJS" -> "React", "node js" -> "Node.js").
- No máximo {max} skills, as mais relevantes.
- Se não houver skill técnica clara, retorne a palavra: NENHUMA

Responda APENAS as skills separadas por vírgula, sem numeração, sem texto extra."""

_GENERIC = {
    "desenvolvimento de software",
    "programacao",
    "programação",
    "tecnologia da informacao",
    "tecnologia da informação",
    "ti",
    "logica",
    "lógica",
    "software",
    "ingles",
    "inglês",
    "espanhol",
    "portugues",
    "português",
    "nenhuma",
    "none",
}


def _clean(raw: str) -> list[str]:
    skills: list[str] = []
    seen: set[str] = set()
    for chunk in raw.replace("\n", ",").split(","):
        name = chunk.strip().strip("-•.").strip()
        if not name or len(name) > 40:
            continue
        canonical = _canonical_skill(name)
        if not canonical or canonical in _GENERIC:
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        skills.append(name)
        if len(skills) >= _MAX_SKILLS:
            break
    return skills


async def extract_tech_skills(
    llm: LLMProvider, profile_text: str, inline_skills: list[str]
) -> list[str]:
    """Skills técnicas do perfil via LLM. Fallback p/ inline (limpo) se falhar."""
    inline_clean = _clean(", ".join(inline_skills)) if inline_skills else []
    if not profile_text:
        return inline_clean
    prompt = _PROMPT.format(
        profile_text=profile_text[:2000],
        inline=", ".join(inline_skills) or "(vazia)",
        max=_MAX_SKILLS,
    )
    try:
        raw = await llm.complete(prompt)
    except Exception as e:
        logger.warning(f"extract_tech_skills LLM falhou: {e}")
        return inline_clean
    extracted = _clean(raw)
    return extracted or inline_clean
