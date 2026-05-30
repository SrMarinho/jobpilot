import unicodedata


def normalize(s: str) -> str:
    """NFKD normalise → strip accents → lowercase. Used for fuzzy matching labels/questions."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def normalize_question(q: str) -> str:
    """Normalise a question/label string, collapsing whitespace."""
    return " ".join(normalize(q).split())
