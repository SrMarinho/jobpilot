import os
import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
QA_FILE = str(_PROJECT_ROOT / ".local" / "files" / "form_answers.json")
_LEGACY_QA_FILE = str(_PROJECT_ROOT / ".local" / "files" / "qa.json")

if os.path.exists(_LEGACY_QA_FILE) and not os.path.exists(QA_FILE):
    try:
        os.rename(_LEGACY_QA_FILE, QA_FILE)
    except Exception:
        pass


def _load_qa_cli() -> dict:
    if os.path.exists(QA_FILE):
        with open(QA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_qa_cli(qa: dict):
    os.makedirs(os.path.dirname(QA_FILE), exist_ok=True)
    with open(QA_FILE, "w", encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=2)


def _qa_display(key: str, entry) -> tuple[str, str, str | None]:
    if isinstance(entry, dict):
        original = entry.get("original") or key
        answer   = entry.get("answer") or ""
        options  = entry.get("options")
        opts_str = ", ".join(options) if options else None
    else:
        original = key
        answer   = str(entry) if entry is not None else ""
        opts_str = None
    return original, answer, opts_str


def _qa_all_entries(qa: dict) -> list[tuple[str, object]]:
    return list(qa.items())


def _is_answered(entry) -> bool:
    if isinstance(entry, dict):
        return bool(entry.get("answer", "").strip())
    return bool(str(entry).strip()) if entry is not None else False


def run_answers_list():
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    missing = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if not missing:
        print("All questions have answers.")
        return
    print(f"{len(missing)} question(s) without an answer:\n")
    for num, key, entry in missing:
        original, _, opts_str = _qa_display(key, entry)
        print(f"  [{num}] {original}")
        if opts_str:
            print(f"       Options: {opts_str}")
    print('\nUse: answers set <number> "your answer"')


def run_answers_show():
    qa = _load_qa_cli()
    if not qa:
        print("No cached answers found.")
        return
    entries = _qa_all_entries(qa)
    answered   = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if     _is_answered(v)]
    unanswered = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if answered:
        print(f"Answered ({len(answered)}):\n")
        for num, key, entry in answered:
            original, answer, opts_str = _qa_display(key, entry)
            print(f"  [{num}] {original}")
            print(f"        A: {answer}")
            if opts_str:
                print(f"        Options: {opts_str}")
    if unanswered:
        print(f"\nMissing ({len(unanswered)}):\n")
        for num, key, entry in unanswered:
            original, _, opts_str = _qa_display(key, entry)
            print(f"  [{num}] {original}")
            if opts_str:
                print(f"        Options: {opts_str}")
        print('\nUse: answers set <number> "your answer"')


def run_answers_set(number: int, answer: str):
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    if number < 1 or number > len(entries):
        print(f"Invalid number {number}. Valid range: 1–{len(entries)}.")
        return
    key, entry = entries[number - 1]
    original, old_answer, _ = _qa_display(key, entry)
    if isinstance(entry, dict):
        entry["answer"] = answer
        qa[key] = entry
    else:
        qa[key] = answer
    _save_qa_cli(qa)
    print(f"[{number}] {original}")
    print(f"  {old_answer!r} -> {answer!r}")


def run_answers_fill():
    qa = _load_qa_cli()
    entries = _qa_all_entries(qa)
    missing = [(i + 1, k, v) for i, (k, v) in enumerate(entries) if not _is_answered(v)]
    if not missing:
        print("All questions already have answers.")
        return
    print(f"{len(missing)} question(s) to fill. Press Enter to skip.\n")
    for num, key, entry in missing:
        original, _, opts_str = _qa_display(key, entry)
        print(f"[{num}] {original}")
        if opts_str:
            print(f"     Options: {opts_str}")
        try:
            value = input("     Answer: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            break
        if not value:
            print("     Skipped.\n")
            continue
        if isinstance(entry, dict):
            entry["answer"] = value
            qa[key] = entry
        else:
            qa[key] = value
        _save_qa_cli(qa)
        print("     Saved.\n")


def run_answers_clear():
    _save_qa_cli({})
    print("All cached answers cleared.")
