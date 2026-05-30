import json
from pathlib import Path

from src.utils.text import normalize_question

_QA_FILE = (
    Path(__file__).parent.parent.parent.parent
    / ".local"
    / "files"
    / "form_answers.json"
)

SALARY_KEYWORDS = [
    "salário",
    "salario",
    "salary",
    "remuneração",
    "remuneracao",
    "pretensão",
    "pretensao",
    "compensation",
    "salarial",
    "expectativa",
    "remuner",
    "wage",
    "pay ",
    "ctc",
]


class FormAnswerCache:
    """Cached form answers — shared between LinkedIn and Indeed handlers."""

    def __init__(self, qa_file: Path | None = None):
        self._qa_file = qa_file or _QA_FILE

    def load(self) -> dict:
        if self._qa_file.exists():
            return json.loads(self._qa_file.read_text(encoding="utf-8"))
        return {}

    def save(self, qa: dict) -> None:
        self._qa_file.parent.mkdir(parents=True, exist_ok=True)
        self._qa_file.write_text(
            json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def resolve(self, question: str) -> str | None:
        qa = self.load()
        key = normalize_question(question)
        entry = qa.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return str(entry.get("answer", "")) if entry.get("answer") else None
        return str(entry) if entry else None

    def store(self, question: str, answer: str, options: list | None = None) -> None:
        qa = self.load()
        key = normalize_question(question)
        if isinstance(qa.get(key), dict):
            qa[key]["answer"] = answer
            if options:
                qa[key]["options"] = options
        elif options:
            qa[key] = {"original": question, "answer": answer, "options": options}
        else:
            qa[key] = answer
        self.save(qa)

    def is_answered(self, question: str) -> bool:
        return bool(self.resolve(question))
