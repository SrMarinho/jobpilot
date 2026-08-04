import re
from src.core.ai.llm_provider import get_eval_provider
from src.core.config.salary_reference import salary_reference_block
from src.core.entities.eval_result import EvalResult
from src.core.use_cases.resume_loader import load_resume_text
from src.config.settings import logger
from src.utils.text import normalize as _normalize

MAX_DESCRIPTION_CHARS = 3000
MAX_DESCRIPTION_CHARS_BATCH = 1500


# Tech stacks and their aliases — used for deterministic filtering
# Each entry: (canonical_name, [keywords_that_identify_it])
_TECH_ALIASES: list[tuple[str, list[str]]] = [
    ("python", ["python", "django", "fastapi", "flask", "sqlalchemy"]),
    ("node", ["node.js", "nodejs", "node js", "express", "nestjs", "nest.js"]),
    ("react", ["react", "next.js", "nextjs"]),
    ("vue", ["vue", "nuxt"]),
    ("angular", ["angular"]),
    ("java", ["java ", "spring boot", "springboot", "quarkus", " java,"]),
    ("dotnet", [".net", "asp.net", "c#", "csharp"]),
    ("php", ["php", "laravel", "symfony", "wordpress"]),
    ("ruby", ["ruby", "rails"]),
    ("go", ["golang", " go ", "go lang"]),
    ("kotlin", ["kotlin"]),
    ("swift", ["swift", "ios developer"]),
    ("powerbuilder", ["powerbuilder", "power builder"]),
]

# Keywords in job titles that indicate each seniority level
_LEVEL_KEYWORDS: dict[str, list[str]] = {
    "senior": [
        "senior",
        "sênior",
        "sr.",
        " sr ",
        " sr",
        "specialist",
        "especialista",
        "lead",
        "principal",
        "staff",
        "head",
        "arquiteto",
        "architect",
    ],
    "pleno": ["pleno", "pl.", "mid", "mid-level", "intermediario", "intermediário"],
    "junior": [
        "junior",
        "júnior",
        "jr.",
        "jr ",
        "trainee",
        "estagiario",
        "estagiário",
        "estágio",
        "estagio",
        "intern",
    ],
}


def _parse_eval_line(line: str) -> EvalResult:
    """Parse a YES/NO eval line (with or without JOB_N prefix stripped).

    Handles both formats:
      YES|7000|reason|skills|CLT
      NO|reason|skills
    """
    for raw in line.splitlines():
        raw = raw.strip()
        upper = raw.upper()
        if not (upper.startswith("YES") or upper.startswith("NO")):
            continue

        parts = raw.split("|")
        is_match = parts[0].strip().upper() == "YES"
        salary: int | None = None
        contract = "unknown"

        if is_match:
            if len(parts) >= 2:
                try:
                    salary = int(re.sub(r"\D", "", parts[1]))
                except Exception:
                    salary = None
            reason = (
                parts[2].strip()
                if len(parts) >= 3
                else (parts[-1].strip() if parts else raw)
            )
            skills_raw = parts[3].strip() if len(parts) >= 4 else ""
            if len(parts) >= 5 and parts[4].strip().upper() in ("CLT", "PJ"):
                contract = parts[4].strip().upper()
        else:
            reason = parts[1].strip() if len(parts) >= 2 else raw
            skills_raw = parts[2].strip() if len(parts) >= 3 else ""

        return EvalResult(
            matches=is_match,
            salary=salary,
            reason=reason,
            missing_skills=[
                s.strip().lower() for s in skills_raw.split(",") if s.strip()
            ],
            contract=contract,
        )

    # Nenhuma linha reconhecível: devolve a resposta crua como motivo.
    return EvalResult(reason=line)


class JobEvaluator:
    def __init__(
        self, resume_path: str, preferences: str = "", level: str | list[str] = ""
    ):
        self.resume = load_resume_text(resume_path)
        self.preferences = preferences
        if isinstance(level, str):
            self.levels = [level] if level else []
        else:
            self.levels = [lv for lv in level if lv]

        # Detect which tech stacks are required from preferences text
        prefs_n = _normalize(preferences)
        self._required_techs: list[str] = [
            name
            for name, keywords in _TECH_ALIASES
            if any(kw in prefs_n for kw in keywords)
        ]

    def quick_reject(self, title: str) -> bool:
        """Returns True if the title can be rejected without an AI call.

        Checks seniority level keywords against the accepted levels.
        If no levels are configured, never quick-rejects.
        """
        if not self.levels:
            return False

        title_n = _normalize(title)
        accepted = {_normalize(lv) for lv in self.levels}

        # Detect which level the title is advertising
        detected = None
        for level, keywords in _LEVEL_KEYWORDS.items():
            if any(kw in title_n for kw in keywords):
                detected = level
                break

        if detected is None:
            return False  # can't tell from title alone — let AI decide

        if detected not in accepted:
            logger.info(
                f"Quick reject (title seniority '{detected}' not in {list(accepted)}): '{title}'"
            )
            return True

        return False

    async def _detect_language(self, text: str) -> str:
        prompt = f"What language is this text written in? Reply with only the language name in English, nothing else.\n\n{text}"
        return await get_eval_provider().complete(prompt)

    def tech_reject(self, title: str, description: str) -> bool:
        """Returns True if the job can be rejected based on tech stack mismatch.

        Only active when required techs are detected in preferences.
        If the description mentions a non-required stack exclusively (no required tech present),
        the job is rejected without an AI call.
        """
        if not self._required_techs:
            return False

        text_n = _normalize(f"{title} {description}")

        # Check if any required tech appears in the job
        has_required = any(
            any(kw in text_n for kw in keywords)
            for name, keywords in _TECH_ALIASES
            if name in self._required_techs
        )
        if has_required:
            return False  # required tech found — let AI decide

        # Check if an incompatible tech appears prominently
        for name, keywords in _TECH_ALIASES:
            if name in self._required_techs:
                continue
            if any(kw in text_n for kw in keywords):
                logger.info(
                    f"Quick reject (tech mismatch — '{name}' not in required {self._required_techs}): '{title}'"
                )
                return True

        return False

    # ── Prompt ───────────────────────────────────────────────────────────────

    def _preferences_section(self) -> str:
        if not self.preferences:
            return ""
        return f"\nCANDIDATE PREFERENCES (prioritize these):\n{self.preferences}\n"

    def _level_rule(self) -> str:
        if not self.levels:
            return "2. Seniority: accept any level.\n"
        accepted = " or ".join(f"'{lv}'" for lv in self.levels)
        return (
            f"2. Seniority: only accept jobs targeting {accepted} level(s). "
            f"If the job is clearly for a different level, answer NO.\n"
        )

    def _build_prompt(self, jobs: list[tuple[str, str]], max_chars: int) -> str:
        """Prompt de avaliação — o mesmo para 1 ou N vagas.

        Single e batch eram dois prompts copiados, com as mesmas regras escritas
        duas vezes: qualquer ajuste em um deixava o outro para trás em silêncio.
        Aqui a única diferença é o prefixo ``JOB_N|`` exigido na resposta quando
        há mais de uma vaga.
        """
        n = len(jobs)
        batch = n > 1
        jobs_section = "".join(
            f"\n--- JOB {i} ---\nTITLE: {title}\nDESCRIPTION:\n{desc[:max_chars]}\n"
            for i, (title, desc) in enumerate(jobs, 1)
        )
        prefix = "JOB_N|" if batch else ""
        header = (
            f"Analyze {n} job listings for the candidate. For EACH job, reply with "
            "exactly ONE line in the format shown."
            if batch
            else "Analyze if this job matches the candidate. "
            "Answer in the exact format shown."
        )
        reply_rule = (
            f"Reply with EXACTLY {n} lines, one per job, in order:"
            if batch
            else "IMPORTANT: reply with ONLY one line, no extra text:"
        )
        examples = (
            "JOB_1|YES|7000|Python/Node backend, remote, pleno|kubernetes|CLT\n"
            "JOB_2|NO|Requires Angular|angular,typescript\n"
            "JOB_3|YES|9000|Node fullstack PJ||PJ"
            if batch
            else "YES|7000|Python/Node backend role, remote, pleno level matches|kubernetes,redis|CLT\n"
            "YES|11000|Pleno PJ Node fullstack remoto|next.js|PJ\n"
            "NO|Requires Angular, candidate works with Python/Node|angular,typescript\n"
            "NO|Go required|golang"
        )

        return f"""{header}

RESUME:
{self.resume}
{self._preferences_section()}{jobs_section}
RULES (answer NO if any fails):
1. Description must be in Portuguese. If English/Spanish → NO.
{self._level_rule()}3. Technologies and preferences must match.
4. Work location: if the description does not explicitly mention on-site or hybrid work, assume it is fully remote and accept it. Only reject if it explicitly requires presential or hybrid attendance.

Contract type detection (look for keywords in description):
- "CLT", "carteira assinada", "consolidação das leis", "registro CLT" → CLT
- "PJ", "pessoa jurídica", "MEI", "contrato PJ", "como PJ" → PJ
- Both mentioned (candidate choice) → pick PJ (higher gross)
- Not mentioned → unknown

{salary_reference_block()}

Use CLT range if contract=CLT, PJ range if contract=PJ. If unknown, default to CLT range (more conservative).

{reply_rule}
If match:    {prefix}YES|<salary number>|<short reason>|<missing skills>|<CLT|PJ|unknown>
If no match: {prefix}NO|<short reason>|<missing skills>

<missing skills>: comma-separated hard skills/technologies the job requires that are NOT in the candidate's resume. Leave empty if none.

Examples:
{examples}"""

    # ── Avaliação ────────────────────────────────────────────────────────────

    async def evaluate_async(self, title: str, description: str) -> EvalResult:
        prompt = self._build_prompt([(title, description)], MAX_DESCRIPTION_CHARS)
        raw = await get_eval_provider().complete(prompt)
        result = _parse_eval_line(raw)
        logger.info(f"Evaluation: {result.summary()}")
        return result

    async def evaluate_batch(self, jobs: list[tuple[str, str]]) -> list[EvalResult]:
        """Avalia N vagas numa chamada só — currículo vai uma vez, ~50% menos tokens."""
        n = len(jobs)
        prompt = self._build_prompt(jobs, MAX_DESCRIPTION_CHARS_BATCH)
        raw = await get_eval_provider().complete(prompt)

        results = [EvalResult.parse_error() for _ in range(n)]
        for line in raw.splitlines():
            line = line.strip()
            if not line.upper().startswith("JOB_"):
                continue
            try:
                prefix, rest = line.split("|", 1)
                idx = int(prefix.strip().split("_")[1]) - 1
            except Exception:
                logger.warning(f"Batch: linha ilegível descartada: {line[:80]!r}")
                continue
            if not 0 <= idx < n:
                logger.warning(f"Batch: índice fora da faixa em {line[:80]!r}")
                continue
            results[idx] = _parse_eval_line(rest)
            logger.info(f"Batch JOB_{idx + 1}: {results[idx].summary()}")

        unparsed = sum(1 for r in results if r.reason == "parse error")
        if unparsed:
            logger.warning(f"Batch: {unparsed}/{n} vagas sem veredito do LLM")
        return results
