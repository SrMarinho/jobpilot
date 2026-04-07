import asyncio
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
from src.config.settings import logger


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
        # Normalize to list
        if isinstance(level, str):
            self.levels = [level] if level else []
        else:
            self.levels = [l for l in level if l]

    def evaluate(self, title: str, description: str) -> bool:
        return asyncio.run(self._evaluate_async(title, description))

    async def _evaluate_async(self, title: str, description: str) -> bool:
        preferences_section = (
            f"\nCANDIDATE PREFERENCES (prioritize these):\n{self.preferences}\n"
            if self.preferences
            else ""
        )

        if self.levels:
            accepted = " or ".join(f"'{l}'" for l in self.levels)
            level_rule = (
                f"2. Seniority level: only accept jobs targeting {accepted} level(s). "
                f"If the job is clearly for a different level, answer NO.\n"
            )
        else:
            level_rule = "2. Seniority level: accept any level.\n"

        prompt = f"""You are a career advisor. Evaluate if this job is a good match for the candidate.

CANDIDATE RESUME:
{self.resume}
{preferences_section}
JOB TITLE: {title}

JOB DESCRIPTION:
{description}

Rules:
1. The job description must be written in Portuguese (pt-BR). If it is in English, Spanish, or any other language, answer NO.
{level_rule}3. Focus on: required technologies, remote vs on-site, contract type, and whether it aligns with the candidate's preferences.

Answer with YES or NO followed by one line of reasoning. Be concise.
Example: YES - The candidate has Python/FastAPI experience matching the requirements and the role is remote.
Example: NO - Job description is in English, not Portuguese.
Example: NO - The job is for Pleno level, not Junior as requested.
Example: NO - The job requires Java expertise which the candidate lacks."""

        result = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(max_turns=1),
        ):
            if isinstance(message, ResultMessage):
                result = message.result

        is_match = result.strip().upper().startswith("YES")
        logger.info(f"Evaluation result: {result.strip()}")
        return is_match
