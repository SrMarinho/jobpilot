"""Classificação de falha de LLM.

Existe porque a diferença entre "o provider caiu" e "o modelo não existe" muda
o que vale fazer: a primeira melhora sozinha com uma nova tentativa, a segunda
nunca melhora — insistir só queima tempo do run. Funções puras (só olham o
texto da exceção), então são testáveis sem rede.
"""

# Modelo/credencial errados: repetir a mesma chamada dá o mesmo erro.
_PERMANENT_MARKERS = (
    "not found",
    "404",
    "does not exist",
    "model_not_found",
    "unknown model",
    "insufficient balance",
    "invalid api key",
    "authentication",
    "unauthorized",
    "401",
    "403",
)

# Sobrecarga/instabilidade: a mesma chamada tende a passar daqui a pouco.
_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "rate limit",
    "rate_limit",
    "429",
    "500",
    "502",
    "503",
    "529",
    "overloaded",
    "connection",
    "temporarily",
    "unknown message type",
    # Ollama subindo: os dois providers chamam _ensure_ollama_running em
    # paralelo e o segundo desiste enquanto o primeiro ainda inicializa.
    "did not start",
)


def _text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".lower()


def is_model_unavailable(exc: BaseException) -> bool:
    """O modelo/credencial atual não serve — trocar de modelo, não repetir."""
    return any(m in _text(exc) for m in _PERMANENT_MARKERS)


def is_transient(exc: BaseException) -> bool:
    """Falha passageira — vale repetir com backoff."""
    text = _text(exc)
    if any(m in text for m in _PERMANENT_MARKERS):
        return False
    return any(m in text for m in _TRANSIENT_MARKERS)
