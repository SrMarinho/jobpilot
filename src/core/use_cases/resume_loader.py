from pathlib import Path

from src.config.settings import logger


def load_resume_text(resume_path: str) -> str:
    """Lê currículo (txt ou pdf). Retorna "" com warning se ausente."""
    p = Path(resume_path)
    if not p.exists():
        logger.warning(f"Resume not found at {resume_path}, using empty context")
        return ""
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(resume_path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return p.read_text(encoding="utf-8", errors="ignore")
