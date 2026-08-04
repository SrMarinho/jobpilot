"""FormAnswerer: cache primeiro, LLM depois.

Testável sem browser e sem rede porque a peça foi separada do DOM e aceita o
provider injetado — é o ponto do refactor do Easy Apply que essa suíte cobre.
"""

import pytest

from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.apply.form_answerer import FormAnswerer
from src.core.use_cases.form_answer_cache import FormAnswerCache


class FakeProvider(LLMProvider):
    """Provider de mentira: conta chamadas e devolve resposta fixa."""

    def __init__(self, answer: str = "resposta do llm", fail: bool = False):
        self.answer = answer
        self.fail = fail
        self.prompts: list[str] = []

    async def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("provider fora do ar")
        return self.answer


@pytest.fixture
def qa_file(tmp_path):
    return tmp_path / "answers.json"


@pytest.fixture
def cache(qa_file):
    # FormAnswerCache já aceita o arquivo por construtor — nada a monkeypatchar.
    return FormAnswerCache(qa_file)


class TestAsk:
    async def test_devolve_a_resposta_do_provider(self, cache):
        provider = FakeProvider("São Paulo")
        answerer = FormAnswerer(cache=cache, provider=provider)
        assert await answerer.ask("Cidade?", "Dev", "descrição") == "São Paulo"

    async def test_prompt_carrega_o_contexto_da_vaga(self, cache):
        provider = FakeProvider()
        answerer = FormAnswerer(cache=cache, provider=provider)
        await answerer.ask("Anos de experiência?", "Dev Backend", "Python e Django")
        prompt = provider.prompts[0]
        assert "Dev Backend" in prompt
        assert "Python e Django" in prompt
        assert "Anos de experiência?" in prompt

    async def test_descricao_e_truncada(self, cache):
        provider = FakeProvider()
        answerer = FormAnswerer(cache=cache, provider=provider)
        await answerer.ask("Q?", "Dev", "x" * 5000)
        assert len(provider.prompts[0]) < 3000

    async def test_falha_do_provider_vira_string_vazia(self, cache):
        answerer = FormAnswerer(cache=cache, provider=FakeProvider(fail=True))
        # Deixar propagar abortaria a candidatura inteira por causa de um campo.
        assert await answerer.ask("Q?", "Dev", "d") == ""

    async def test_provider_injetado_nao_e_reconstruido(self, cache):
        provider = FakeProvider()
        answerer = FormAnswerer(cache=cache, provider=provider)
        assert await answerer.provider() is provider
        assert await answerer.provider() is provider


class TestAnswer:
    async def test_cache_vazio_consulta_o_llm(self, cache):
        provider = FakeProvider("5 anos")
        answerer = FormAnswerer(cache=cache, provider=provider)
        resposta, do_cache = await answerer.answer("Experiência?", "Dev", "d")
        assert (resposta, do_cache) == ("5 anos", False)
        assert len(provider.prompts) == 1

    async def test_resposta_guardada_evita_nova_chamada(self, cache):
        provider = FakeProvider("5 anos")
        answerer = FormAnswerer(cache=cache, provider=provider)
        answerer.store("Experiência?", "5 anos")
        resposta, do_cache = await answerer.answer("Experiência?", "Dev", "d")
        assert (resposta, do_cache) == ("5 anos", True)
        assert provider.prompts == []

    async def test_options_entram_no_prompt(self, cache):
        provider = FakeProvider()
        answerer = FormAnswerer(cache=cache, provider=provider)
        await answerer.answer("Nível?", "Dev", "d", options=["Junior", "Pleno"])
        assert "Junior" in provider.prompts[0] and "Pleno" in provider.prompts[0]


class TestCache:
    def test_resolve_devolve_none_quando_nao_conhece(self, cache):
        assert FormAnswerer(cache=cache).resolve("pergunta inédita") is None

    def test_store_e_resolve(self, cache):
        answerer = FormAnswerer(cache=cache)
        answerer.store("Cidade?", "São Paulo")
        assert answerer.resolve("Cidade?") == "São Paulo"

    def test_cache_persiste_entre_instancias(self, cache, qa_file):
        FormAnswerer(cache=cache).store("Cidade?", "Recife")
        outro = FormAnswerer(cache=FormAnswerCache(qa_file))
        assert outro.resolve("Cidade?") == "Recife"
