from src.core.use_cases.resume_loader import load_resume_text


def read_resume_text(resume_path: str) -> str:
    return load_resume_text(resume_path)
