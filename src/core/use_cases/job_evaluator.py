import re
import unicodedata
import asyncio
from pathlib import Path
from src.core.ai.llm_provider import get_eval_provider
from src.config.settings import logger

MAX_DESCRIPTION_CHARS = 3000
MAX_DESCRIPTION_CHARS_BATCH = 1500


# Tech stacks and their aliases — used for deterministic filtering
# Each entry: (canonical_name, [keywords_that_identify_it])
_TECH_ALIASES: list[tuple[str, list[str]]] = [
    ("python",     ["python", "django", "fastapi", "flask", "sqlalchemy"]),
    ("node",       ["node.js", "nodejs", "node js", "express", "nestjs", "nest.js"]),
    ("react",      ["react", "next.js", "nextjs"]),
    ("vue",        ["vue", "nuxt"]),
    ("angular",    ["angular"]),
    ("java",       ["java ", "spring boot", "springboot", "quarkus", " java,"]),
    ("dotnet",     [".net", "asp.net", "c#", "csharp"]),
    ("php",        ["php", "laravel", "symfony", "wordpress"]),
    ("ruby",       ["ruby", "rails"]),
    ("go",         ["golang", " go ", "go lang"]),
    ("kotlin",     ["kotlin"]),
    ("swift",      ["swift", "ios developer"]),
    ("powerbuilder", ["powerbuilder", "power builder"]),
]

# Keywords in job titles that indicate each seniority level
_LEVEL_KEYWORDS: dict[str, list[str]] = {
    "senior":    ["senior", "sênior", "sr.", " sr ", " sr", "specialist", "especialista",
                  "lead", "principal", "staff", "head", "arquiteto", "architect"],
    "pleno":     ["pleno", "pl.", "mid", "mid-level", "intermediario", "intermediário"],
    "junior":    ["junior", "júnior", "jr.", "jr ", "trainee", "estagiario",
                  "estagiário", "estágio", "estagio", "intern"],
}

def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _parse_eval_line(line: str) -> tuple[bool, int | None, str, list[str], str]:
    """Parse a YES/NO eval line (with or without JOB_N prefix stripped).

    Handles both formats:
      YES|7000|reason|skills|CLT
      NO|reason|skills
    """
    is_match = False
    salary: int | None = None
    reason = line
    missing_skills: list[str] = []
    contract_type = "unknown"

    for raw in line.splitlines():
        raw = raw.strip()
        upper = raw.upper()
        if upper.startswith("YES") or upper.startswith("NO"):
            parts = raw.split("|")
            is_match = parts[0].strip().upper() == "YES"
            if is_match and len(parts) >= 2:
                try:
                    salary = int(re.sub(r"\D", "", parts[1]))
                except Exception:
                    salary = None
            if is_match:
                reason = parts[2].strip() if len(parts) >= 3 else (parts[-1].strip() if parts else raw)
                skills_raw = parts[3].strip() if len(parts) >= 4 else ""
                if len(parts) >= 5:
                    ct_raw = parts[4].strip().upper()
                    if ct_raw in ("CLT", "PJ"):
                        contract_type = ct_raw
            else:
                reason = parts[1].strip() if len(parts) >= 2 else raw
                skills_raw = parts[2].strip() if len(parts) >= 3 else ""
            missing_skills = [s.strip().lower() for s in skills_raw.split(",") if s.strip()]
            break

    return is_match, salary, reason, missing_skills, contract_type


class JobEvaluator:
    def __init__(self, resume_path: str, preferences: str = "", level: str | list[str] = ""):
        path = Path(resume_path)
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(resume_path)
            self.resume = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            with open(resume_path, "r", encoding="utf-8") as f:
                self.resume = f.read()
        self.preferences = preferences
        if isinstance(level, str):
            self.levels = [level] if level else []
        else:
            self.levels = [l for l in level if l]

        # Detect which tech stacks are required from preferences text
        prefs_n = _normalize(preferences)
        self._required_techs: list[str] = [
            name for name, keywords in _TECH_ALIASES
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
        accepted = {_normalize(l) for l in self.levels}

        # Detect which level the title is advertising
        detected = None
        for level, keywords in _LEVEL_KEYWORDS.items():
            if any(kw in title_n for kw in keywords):
                detected = level
                break

        if detected is None:
            return False  # can't tell from title alone — let AI decide

        if detected not in accepted:
            logger.info(f"Quick reject (title seniority '{detected}' not in {list(accepted)}): '{title}'")
            return True

        return False

    def language_reject(self, description: str) -> bool:
        """Returns True if the description is not in Portuguese (AI-based detection)."""
        snippet = description[:400].strip()
        if not snippet:
            return False
        try:
            lang = asyncio.run(self._detect_language(snippet))
            if "portuguese" not in lang.lower():
                logger.info(f"Quick reject (language: '{lang.strip()}')")
                return True
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
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
                logger.info(f"Quick reject (tech mismatch — '{name}' not in required {self._required_techs}): '{title}'")
                return True

        return False

    def evaluate(self, title: str, description: str) -> tuple[bool, int | None, str, list[str], str]:
        """Returns (is_match, salary_estimate, reason, missing_skills, contract_type).

        contract_type: 'CLT' | 'PJ' | 'unknown'. Salary is tuned to whichever was detected.
        """
        return asyncio.run(self.evaluate_async(title, description))

    async def evaluate_async(self, title: str, description: str) -> tuple[bool, int | None, str, list[str], str]:
        description = description[:MAX_DESCRIPTION_CHARS]

        preferences_section = (
            f"\nCANDIDATE PREFERENCES (prioritize these):\n{self.preferences}\n"
            if self.preferences else ""
        )

        if self.levels:
            accepted = " or ".join(f"'{l}'" for l in self.levels)
            level_rule = (
                f"2. Seniority: only accept jobs targeting {accepted} level(s). "
                f"If the job is clearly for a different level, answer NO.\n"
            )
        else:
            level_rule = "2. Seniority: accept any level.\n"

        prompt = f"""Analyze if this job matches the candidate. Answer in the exact format shown.

RESUME:
{self.resume}
{preferences_section}
JOB TITLE: {title}
JOB DESCRIPTION:
{description}

RULES (answer NO if any fails):
1. Description must be in Portuguese. If English/Spanish → NO.
{level_rule}3. Technologies and preferences must match.
4. Work location: if the description does not explicitly mention on-site or hybrid work, assume it is fully remote and accept it. Only reject if it explicitly requires presential or hybrid attendance.

Contract type detection (look for keywords in description):
- "CLT", "carteira assinada", "consolidação das leis", "registro CLT" → CLT
- "PJ", "pessoa jurídica", "MEI", "contrato PJ", "como PJ" → PJ
- Both mentioned (candidate choice) → pick PJ (higher gross)
- Not mentioned → unknown

Salary reference (BRL/month):
- Junior CLT 3000-6000 | Junior PJ 4000-8000
- Pleno  CLT 6000-10000 | Pleno  PJ 8000-14000
- Senior CLT 10000-18000 | Senior PJ 14000-25000

Use CLT range if contract=CLT, PJ range if contract=PJ. If unknown, default to CLT range (more conservative).

IMPORTANT: reply with ONLY one line, no extra text:
If match: YES|<salary number>|<short reason>|<missing skills>|<CLT|PJ|unknown>
If no match: NO|<short reason>|<missing skills>

<missing skills>: comma-separated hard skills/technologies the job requires that are NOT in the candidate's resume. Leave empty if none.

Examples:
YES|7000|Python/Node backend role, remote, pleno level matches|kubernetes,redis|CLT
YES|11000|Pleno PJ Node fullstack remoto|next.js|PJ
NO|Requires Angular, candidate works with Python/Node|angular,typescript
NO|Go required|golang"""

        result = await get_eval_provider().complete(prompt)
        parsed = _parse_eval_line(result)
        is_match, salary, reason, missing_skills, contract_type = parsed
        logger.info(f"Evaluation: {'YES' if is_match else 'NO'} | salary={salary} | contract={contract_type} | {reason}" +
                    (f" | missing: {missing_skills}" if missing_skills else ""))
        return parsed

    async def evaluate_batch(
        self, jobs: list[tuple[str, str]]
    ) -> list[tuple[bool, int | None, str, list[str], str]]:
        """Evaluate N jobs in a single LLM call. Resume sent once — saves ~50% tokens vs N individual calls."""
        n = len(jobs)

        preferences_section = (
            f"\nCANDIDATE PREFERENCES (prioritize these):\n{self.preferences}\n"
            if self.preferences else ""
        )

        if self.levels:
            accepted = " or ".join(f"'{l}'" for l in self.levels)
            level_rule = (
                f"2. Seniority: only accept jobs targeting {accepted} level(s). "
                f"If the job is clearly for a different level, answer NO.\n"
            )
        else:
            level_rule = "2. Seniority: accept any level.\n"

        jobs_section = ""
        for i, (title, description) in enumerate(jobs, 1):
            jobs_section += (
                f"\n--- JOB {i} ---\n"
                f"TITLE: {title}\n"
                f"DESCRIPTION:\n{description[:MAX_DESCRIPTION_CHARS_BATCH]}\n"
            )

        prompt = f"""Analyze {n} job listings for the candidate. For EACH job, reply with exactly ONE line in the format shown.

RESUME:
{self.resume}
{preferences_section}{jobs_section}
RULES (apply to ALL jobs):
1. Description must be in Portuguese. If English/Spanish → NO.
{level_rule}3. Technologies and preferences must match.
4. Work location: if not explicitly on-site or hybrid, assume remote and accept.

Contract type detection:
- "CLT", "carteira assinada" → CLT
- "PJ", "pessoa jurídica", "MEI" → PJ
- Both → pick PJ | Not mentioned → unknown

Salary reference (BRL/month):
- Junior CLT 3000-6000 | Junior PJ 4000-8000
- Pleno  CLT 6000-10000 | Pleno  PJ 8000-14000
- Senior CLT 10000-18000 | Senior PJ 14000-25000

Reply with EXACTLY {n} lines, one per job, in order:
If match:    JOB_N|YES|<salary>|<short reason>|<missing skills>|<CLT|PJ|unknown>
If no match: JOB_N|NO|<short reason>|<missing skills>

<missing skills>: comma-separated techs NOT in resume. Leave empty if none.

Examples:
JOB_1|YES|7000|Python/Node backend, remote, pleno|kubernetes|CLT
JOB_2|NO|Requires Angular|angular,typescript
JOB_3|YES|9000|Node fullstack PJ||PJ"""

        result = await get_eval_provider().complete(prompt)

        default: tuple[bool, int | None, str, list[str], str] = (False, None, "parse error", [], "unknown")
        results: list[tuple[bool, int | None, str, list[str], str]] = [default] * n

        for line in result.splitlines():
            line = line.strip()
            upper = line.upper()
            if upper.startswith("JOB_"):
                try:
                    prefix, rest = line.split("|", 1)
                    idx = int(prefix.strip().split("_")[1]) - 1
                    if 0 <= idx < n:
                        parsed = _parse_eval_line(rest)
                        results[idx] = parsed
                        is_match, salary, reason, missing_skills, contract_type = parsed
                        logger.info(
                            f"Batch JOB_{idx+1}: {'YES' if is_match else 'NO'} | salary={salary} | {reason}" +
                            (f" | missing: {missing_skills}" if missing_skills else "")
                        )
                except Exception:
                    pass

        return results
