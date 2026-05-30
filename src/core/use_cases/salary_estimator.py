from src.core.ai.llm_provider import get_llm_provider
from src.config.settings import logger


class SalaryEstimator:
    """Estimates an appropriate salary expectation based on the job and candidate's resume."""

    def __init__(self, resume: str = ""):
        self.resume = resume

    async def _estimate_async(self, title: str, description: str) -> int | None:
        prompt = f"""You are a Brazilian tech salary expert. Based on the candidate's resume and the job posting, suggest an appropriate salary expectation to put on their application.

CANDIDATE RESUME:
{self.resume}

JOB TITLE: {title}

JOB DESCRIPTION:
{description}

Instructions:
1. Check if the job description mentions a salary range or value — if yes, use it as the primary reference.
2. Identify the seniority level (Junior, Pleno, Sênior) from the job title/description.
3. Identify the contract type (CLT or PJ) if mentioned.
4. Consider the candidate's actual experience from the resume to calibrate within the market range.
5. Suggest a realistic value — not too high (would get rejected) and not too low (would undervalue the candidate).

Market reference (monthly gross, BRL):
- Junior Dev: CLT R$3.000–6.000 | PJ R$4.000–8.000
- Pleno Dev: CLT R$6.000–10.000 | PJ R$8.000–14.000
- Sênior Dev: CLT R$10.000–18.000 | PJ R$14.000–25.000

Reply with ONLY a single integer representing the suggested monthly salary in BRL (no currency symbol, no dots, no text).
Example: 5000"""

        result = await get_llm_provider().complete(prompt)

        try:
            # Extract first number found in the response
            import re

            match = re.search(r"\d[\d.]*", result.replace(",", ""))
            if match:
                value = int(match.group().replace(".", ""))
                logger.info(f"Salary estimate: R${value:,}")
                return value
        except Exception:
            pass

        logger.warning(f"Could not parse salary estimate from: '{result}'")
        return None
