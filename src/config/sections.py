"""Configuração agrupada por domínio.

Antes cada consumidor lia sua própria env direto do ``os.getenv``, espalhado
por 21 arquivos — sem lugar único pra descobrir quais variáveis existem, e com
o nome e a headline do usuário chumbados como default em cinco arquivos
diferentes ("Matheus Marinho"), o que fazia o projeto postar com a identidade
errada em qualquer outra máquina.

Cada seção é um objeto com propriedades que leem a env **na hora do acesso** —
não no import — porque o bot e alguns comandos ajustam ``os.environ`` em runtime.
"""

from src.config.env import env_bool, env_int, env_required, env_str


class TelegramSettings:
    """Credenciais do bot. Ausentes => features de Telegram viram no-op."""

    @property
    def token(self) -> str:
        return env_str("TELEGRAM_BOT_TOKEN")

    @property
    def chat_id(self) -> str:
        return env_str("TELEGRAM_CHAT_ID")

    @property
    def admin_id(self) -> str:
        """DM do admin; cai no chat do grupo quando não configurado."""
        return env_str("TELEGRAM_ADMIN_ID") or self.chat_id

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)


class UserSettings:
    """Identidade usada em posts, comentários e DMs.

    Obrigatória de propósito: um default aqui significa publicar no LinkedIn
    assinando com o nome de outra pessoa.
    """

    @property
    def name(self) -> str:
        return env_required("USER_NAME", hint="É o nome que assina posts e DMs.")

    @property
    def headline(self) -> str:
        return env_required(
            "USER_HEADLINE", hint="É a headline usada no contexto dos posts."
        )

    @property
    def profile_slug(self) -> str:
        """Parte final do URL do perfil: ``/in/<slug>/``."""
        return env_str("LINKEDIN_PROFILE_SLUG")

    def as_dict(self) -> dict:
        return {"user_name": self.name, "user_headline": self.headline}


class EngageSettings:
    """Ajustes do engajamento no feed (todos opcionais).

    O pipeline multi-modelo é o padrão: um modelo forte gera o comentário, um
    barato critica e um mínimo comprime — daí os três defaults distintos.
    """

    GENERATOR_DEFAULT = "claude-sonnet-5"
    REVIEWER_DEFAULT = "claude-fable-5"
    COMPRESSOR_DEFAULT = "claude-haiku-4-5-20251001"

    @property
    def generator_model(self) -> str:
        return env_str("ENGAGE_GENERATOR_MODEL", self.GENERATOR_DEFAULT)

    @property
    def reviewer_model(self) -> str:
        return env_str("ENGAGE_REVIEWER_MODEL", self.REVIEWER_DEFAULT)

    @property
    def compressor_model(self) -> str:
        return env_str("ENGAGE_COMPRESSOR_MODEL", self.COMPRESSOR_DEFAULT)

    @property
    def min_caption_words(self) -> int:
        """Legenda mais curta que isso não tem conteúdo pra comentar em cima."""
        return env_int("ENGAGE_MIN_CAPTION_WORDS", 40)

    @property
    def claude_pipeline(self) -> bool:
        return env_bool("ENGAGE_CLAUDE_PIPELINE", True)

    @property
    def skip_relevance(self) -> bool:
        return env_bool("ENGAGE_SKIP_RELEVANCE", False)

    @property
    def author_dev_only(self) -> bool:
        """Só engaja com post de quem é da área — evita comentário fora de contexto."""
        return env_bool("ENGAGE_AUTHOR_DEV_ONLY", True)

    @property
    def question_only(self) -> bool:
        return env_bool("ENGAGE_QUESTION_ONLY", True)


class AutopostSettings:
    """Modelos do pipeline de post autoral (gera / revisa)."""

    @property
    def generator_model(self) -> str:
        return env_str("AUTOPOST_GENERATOR_MODEL")

    @property
    def reviewer_model(self) -> str:
        return env_str("AUTOPOST_REVIEWER_MODEL")


telegram = TelegramSettings()
user = UserSettings()
engage = EngageSettings()
autopost = AutopostSettings()
