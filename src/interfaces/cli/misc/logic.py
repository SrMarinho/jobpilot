from pathlib import Path as _Path


def read_resume_text(resume_path: str) -> str:
    rp = _Path(resume_path)
    if rp.suffix.lower() == ".pdf":
        from pypdf import PdfReader as _PdfReader

        return "\n".join(p.extract_text() or "" for p in _PdfReader(resume_path).pages)
    return rp.read_text(encoding="utf-8")
