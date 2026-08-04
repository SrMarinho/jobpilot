"""Filtros que decidem o que o bot comenta e publica.

São a última barreira antes de algo ir pro LinkedIn com o nome do usuário:
um falso negativo aqui vira comentário alucinado ou clichê em post público.
"""

import pytest

from src.core.use_cases.comment_filters import (
    comment_is_grounded,
    is_cliche,
    is_refusal,
    is_trivial,
)
from src.core.use_cases.content_filters import (
    content_tokens,
    has_tech_keyword,
    post_asks_question,
    strip_noise,
)


class TestGrounding:
    def test_comentario_que_cita_o_post_passa(self):
        post = "Migramos nossa API de Django para FastAPI e o p99 caiu pela metade."
        assert comment_is_grounded("A migração pra FastAPI valeu pelo p99?", post)

    def test_comentario_sem_relacao_e_barrado(self):
        post = "Migramos nossa API de Django para FastAPI."
        assert not comment_is_grounded(
            "Excelente reflexão sobre liderança e cultura organizacional", post
        )

    def test_comentario_vazio_nao_e_grounded(self):
        assert not comment_is_grounded("", "qualquer post com conteúdo")

    def test_tolera_flexao_da_palavra(self):
        # Compara por prefixo de 5 chars: "migração" casa com "migramos".
        assert comment_is_grounded("A migração foi tranquila?", "Migramos o serviço")


class TestCliche:
    @pytest.mark.parametrize(
        "texto", ["Ótimo post!", "otimo post", "Concordo!", "Muito bom!", "   "]
    )
    def test_baixo_esforco_e_barrado(self, texto):
        assert is_cliche(texto)

    def test_comentario_com_substancia_passa(self):
        assert not is_cliche("Curioso: vocês mediram o p99 antes de migrar?")

    def test_so_barra_quando_e_a_frase_inteira(self):
        assert not is_cliche("Ótimo post, mas fiquei com dúvida no benchmark.")


class TestRefusal:
    @pytest.mark.parametrize(
        "texto",
        [
            "Retornar string vazia, pois não há conteúdo técnico.",
            "Não há conteúdo técnico suficiente para comentar.",
            "O post é puramente promocional.",
            "Não vou comentar neste post.",
        ],
    )
    def test_modelo_explicando_que_nao_comenta(self, texto):
        assert is_refusal(texto)

    def test_comentario_de_verdade_nao_e_recusa(self):
        assert not is_refusal("Vocês usaram índice parcial nessa query?")

    def test_texto_vazio(self):
        assert not is_refusal("")


class TestTrivial:
    @pytest.mark.parametrize(
        "texto",
        [
            "O que é Kubernetes?",
            "Para que serve o Redis?",
            "Como o cache funciona?",
            "What is Docker?",
        ],
    )
    def test_pergunta_de_iniciante_e_barrada(self, texto):
        assert is_trivial(texto)

    def test_pergunta_de_senior_passa(self):
        assert not is_trivial(
            "Vocês usaram HPA por CPU ou por métrica custom nesse cluster?"
        )


class TestTechKeyword:
    def test_post_tecnico(self):
        assert has_tech_keyword("Refatorei o backend em Python com FastAPI")

    def test_post_motivacional(self):
        assert not has_tech_keyword(
            "Hoje completo mais um ano de jornada. Gratidão a todos!"
        )


class TestPostAsksQuestion:
    def test_com_pergunta(self):
        assert post_asks_question("Como vocês lidam com isso no dia a dia?")

    def test_sem_pergunta(self):
        assert not post_asks_question("Publiquei um artigo novo sobre observabilidade.")


class TestTokens:
    def test_strip_noise_nao_quebra_em_texto_limpo(self):
        assert strip_noise("Texto simples").strip() != ""

    def test_content_tokens_ignora_palavras_vazias(self):
        tokens = content_tokens("o time de dados usou Kubernetes para o cluster")
        assert "kubernetes" in tokens
        # Artigos e preposições não são conteúdo.
        assert "de" not in tokens and "o" not in tokens
