"""A classificação decide se vale repetir ou trocar de modelo — se ela erra,
o run ou insiste num 404 ou desiste de uma falha passageira."""

import pytest

from src.core.ai.llm_errors import is_model_unavailable, is_transient


@pytest.mark.parametrize(
    "message",
    [
        "model 'claude-sonnet-5' not found (status code: 404)",
        "Error code: 402 - {'error': {'message': 'Insufficient Balance'}}",
        "unknown model: qwen9:1t",
        "401 Unauthorized",
    ],
)
def test_erro_permanente_e_reconhecido(message):
    assert is_model_unavailable(RuntimeError(message))
    assert not is_transient(RuntimeError(message))


@pytest.mark.parametrize(
    "message",
    [
        "Request timed out",
        "rate limit exceeded, retry after 30s",
        "503 Service Unavailable",
        "Connection refused",
        "Unknown message type: rate_limit_event",
    ],
)
def test_erro_transitorio_e_reconhecido(message):
    assert is_transient(RuntimeError(message))
    assert not is_model_unavailable(RuntimeError(message))


def test_erro_sem_marcador_nao_e_repetido_nem_trocado():
    exc = ValueError("prompt vazio")
    assert not is_transient(exc)
    assert not is_model_unavailable(exc)


def test_permanente_ganha_de_transitorio_na_mesma_mensagem():
    # "404 ... timeout": insistir não resolve; o 404 manda.
    exc = RuntimeError("model not found (404) after timeout")
    assert is_model_unavailable(exc)
    assert not is_transient(exc)


def test_ollama_ainda_subindo_e_transitorio():
    # Os dois providers chamam _ensure_ollama_running em paralelo; o segundo
    # desiste enquanto o primeiro ainda inicializa. Repetir resolve.
    exc = RuntimeError("Ollama did not start within 15s at http://localhost:11434")
    assert is_transient(exc)
    assert not is_model_unavailable(exc)
