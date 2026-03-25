import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
from src.config.settings import logger


class JobEvaluator:
    def __init__(self, resume_path: str, preferences: str = ""):
        with open(resume_path, "r", encoding="utf-8") as f:
            self.resume = f.read()
        self.preferences = preferences

    def evaluate(self, title: str, description: str) -> bool:
        return asyncio.run(self._evaluate_async(title, description))

    async def _evaluate_async(self, title: str, description: str) -> bool:
        preferences_section = (
            f"\nCANDIDATE PREFERENCES (prioritize these):\n{self.preferences}\n"
            if self.preferences
            else ""
        )

        prompt = f"""You are a career advisor. Evaluate if this job is a good match for the candidate.

CANDIDATE RESUME:
{self.resume}
{preferences_section}
JOB TITLE: {title}

JOB DESCRIPTION:
{description}

Answer with YES or NO followed by one line of reasoning. Be concise.
Example: YES - The candidate has 3+ years of Python experience matching the requirements.
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
