"""Cura de selector dentro do run, com o DOM ainda vivo.

É aqui que o laço fecha: o resolver falhou, o DOM ainda está na tela, e este
módulo descreve a página, pede candidatos ao LLM, valida na própria página e
persiste o que passou — devolvendo o Locator para o run continuar de onde
parou, no mesmo segundo.

Curar dentro do run é o que dá precisão (o DOM que causou a falha é o que o
modelo vê), mas cobra caro: isso acontece **com o lock do browser na mão**, e o
lock tem teto de 600s que já foi estourado duas vezes em setembro. Por isso os
tetos daqui são duros e pequenos — dois campos por run, um minuto no total.

Ordem das checagens é de propósito a mais barata primeiro: registry, store,
quota, checkpoint, e só então LLM. Nenhuma delas custa rede; a última custa.

Regra que atravessa o módulo: **nada aqui pode derrubar o run**. O run agendado
é a única chance do dia. Toda falha vira log e ``None``, e o resolver segue
pelo caminho que seguiria se esta feature não existisse.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from playwright.async_api import Locator, Page

from src.config.env import env_int
from src.config.settings import logger
from src.core.use_cases.evolve.heal_prompt import build_heal_prompt, parse_candidates
from src.core.use_cases.evolve.selector_registry import spec_for
from src.core.use_cases.evolve.selector_store import refresh_overrides, store

MAX_HEALS_PER_RUN = env_int("EVOLVE_MAX_HEALS_PER_RUN", 2)
MAX_HEAL_SECONDS_PER_RUN = env_int("EVOLVE_MAX_HEAL_SECONDS_PER_RUN", 60)


def enabled() -> bool:
    """Kill switch. Desligado por default até o dono ligar."""
    return os.getenv("EVOLVE_HEAL", "false").strip().lower() in {"1", "true", "yes"}


@dataclass(slots=True)
class HealBudget:
    """Orçamento de cura de um run. Vive só na memória do processo."""

    max_heals: int = MAX_HEALS_PER_RUN
    max_seconds: int = MAX_HEAL_SECONDS_PER_RUN
    heals: int = 0
    seconds: float = 0.0
    fields_tried: set[str] = field(default_factory=set)

    def blocks(self, field_name: str) -> str:
        """Motivo para não curar agora, ou string vazia."""
        if field_name in self.fields_tried:
            # Duas curas do mesmo campo no mesmo run significam que a primeira
            # não resolveu; insistir só queima orçamento.
            return "campo já tentado neste run"
        if self.heals >= self.max_heals:
            return f"teto de {self.max_heals} curas por run"
        if self.seconds >= self.max_seconds:
            return f"teto de {self.max_seconds}s de cura por run"
        return ""

    def spend(self, field_name: str, seconds: float, *, healed: bool) -> None:
        self.fields_tried.add(field_name)
        self.seconds += seconds
        if healed:
            self.heals += 1


class SelectorHealer:
    """Gancho de cura instalável em ``selectors.set_heal_hook``."""

    def __init__(self, page: Page, *, budget: HealBudget | None = None, provider=None):
        self.page = page
        self.budget = budget or HealBudget()
        self._provider = provider
        self.healed: list[tuple[str, str]] = []

    def provider(self):
        # Lazy: um run que nunca precisa de cura não paga import de provider
        # nem warmup de modelo.
        if self._provider is None:
            from src.core.ai.llm_provider import get_llm_provider

            self._provider = get_llm_provider()
        return self._provider

    async def __call__(
        self,
        root: Page | Locator,
        selectors: list[str],
        *,
        field: str,
        kind: str = "visible",
    ) -> Locator | None:
        try:
            return await self._heal(root, selectors, field=field, kind=kind)
        except Exception as e:
            # Última rede: o resolver chama isto de dentro do loop de scraping.
            logger.warning(f"[evolve] cura abortou campo={field!r}: {e}")
            return None

    async def _heal(
        self,
        root: Page | Locator,
        selectors: list[str],
        *,
        field: str,
        kind: str,
    ) -> Locator | None:
        if not enabled():
            return None

        spec = spec_for(field)
        if spec is None:
            logger.info(
                f"[evolve] campo={field!r} não está no registry — sem cura "
                "(declare em selector_registry para habilitar)"
            )
            return None
        if not spec.healable:
            logger.info(
                f"[evolve] campo={field!r} não é curável: "
                f"{spec.absent_note or 'clicável sem expect declarado'}"
            )
            return None

        motivo = self.budget.blocks(field)
        if motivo:
            logger.info(f"[evolve] cura pulada campo={field!r}: {motivo}")
            return None

        current = store()
        override = current.override(field)
        if override.unhealable:
            logger.info(f"[evolve] campo={field!r} marcado incurável: {override.note}")
            return None
        if override.in_cooldown():
            logger.info(
                f"[evolve] campo={field!r} em cooldown "
                f"(última tentativa {override.last_heal_attempt})"
            )
            return None

        if not self._quota_ok():
            return None
        if await self._blocked_by_checkpoint():
            return None

        started = time.monotonic()
        healed = await self._ask_and_validate(root, selectors, spec, kind)
        elapsed = time.monotonic() - started
        self.budget.spend(field, elapsed, healed=healed is not None)
        return healed

    def _quota_ok(self) -> bool:
        try:
            from src.core.use_cases.rate_limiter import RateLimiter

            status = RateLimiter().check("heal")
            if not status:
                logger.warning(f"[evolve] cura bloqueada: {status.reason}")
                return False
        except Exception as e:
            # Sem quota legível, o conservador é NÃO curar: gasto de LLM sem
            # teto é pior que um campo quebrado que já está sendo reportado.
            logger.warning(f"[evolve] quota de cura indisponível ({e}) — não cura")
            return False
        return True

    async def _blocked_by_checkpoint(self) -> bool:
        """Sob CAPTCHA o DOM não é a página real — a cura aprenderia lixo."""
        try:
            from src.automation.checkpoint import detect_checkpoint

            found = await detect_checkpoint(self.page)
        except Exception:
            return False
        if found:
            logger.warning(f"[evolve] cura pulada: checkpoint detectado ({found})")
            return True
        return False

    async def _ask_and_validate(
        self, root, selectors: list[str], spec, kind: str
    ) -> Locator | None:
        from src.automation.evolve import candidate_validator, dom_context

        contexto = await dom_context.capture(root, scope=spec.scope)
        prompt = build_heal_prompt(
            field=spec.field,
            intent=spec.intent,
            scope=spec.scope,
            kind=kind,
            failed=list(selectors),
            dom_context=contexto,
            expect=spec.expect,
            max_matches=spec.max_matches,
        )

        logger.info(f"[evolve] pedindo candidatos para campo={spec.field!r}")
        try:
            raw = await self.provider().complete(prompt)
        except Exception as e:
            logger.warning(f"[evolve] LLM falhou na cura de {spec.field!r}: {e}")
            store().note_heal_attempt(spec.field, ok=False)
            return None

        candidatos = parse_candidates(raw)
        if not candidatos:
            logger.warning(
                f"[evolve] LLM não devolveu candidato utilizável para "
                f"campo={spec.field!r} (resposta: {raw[:120]!r})"
            )
            store().note_heal_attempt(spec.field, ok=False)
            return None

        aprovado, laudos = await candidate_validator.first_valid(
            root, candidatos, spec, kind=kind
        )
        current = store()
        if aprovado is None:
            motivos = "; ".join(f"{v.selector!r}: {v.reason}" for v in laudos)
            logger.warning(
                f"[evolve] nenhum candidato passou a validação campo="
                f"{spec.field!r} — {motivos}"
            )
            current.note_heal_attempt(spec.field, ok=False)
            current.flush()
            return None

        current.learn(spec.field, aprovado.selector)
        current.note_heal_attempt(spec.field, ok=True)
        current.flush()
        refresh_overrides()

        self.healed.append((spec.field, aprovado.selector))
        logger.info(
            f"[evolve] cura aplicada campo={spec.field!r} -> {aprovado.selector!r} "
            f"(nome={aprovado.name!r})"
        )
        self._record_quota()
        self._enqueue_promotion(spec, aprovado)
        self._notify(spec.field, aprovado)

        return candidate_validator.resolve(root, aprovado.selector).first

    def _enqueue_promotion(self, spec, validation) -> None:
        """Pede que o drain leve o selector aprendido pro código-fonte.

        Sem isso o override vive só no banco, e o código-fonte passa a mentir:
        quem lê a page vê a lista antiga, o git não registra nada, e uma máquina
        nova começa com o selector morto. Enfileirar aqui e promover no drain é
        o que mantém banco e código convergindo — sem segurar o lock do browser
        pelos minutos que ruff, pytest e smoke levam.
        """
        try:
            from src.core.use_cases.evolve.queue import (
                KIND_PROMOTE_SELECTOR,
                EvolutionQueue,
            )

            EvolutionQueue().enqueue(
                KIND_PROMOTE_SELECTOR,
                {
                    "field": spec.field,
                    "selector": validation.selector,
                    "module": spec.module,
                    "constant": spec.constant,
                    "evidence": {
                        "matches": validation.matches,
                        "name": validation.name,
                    },
                    "commit_subject": f"promove selector aprendido de {spec.field}",
                    "commit_body": (
                        f"O candidato declarado de {spec.field!r} parou de casar e a "
                        f"cura em runtime validou {validation.selector!r} contra o DOM "
                        f"(1 elemento visível, nome acessível {validation.name!r}).\n\n"
                        "Entra como primeiro candidato porque é o layout atual; os "
                        "declarados abaixo seguem como fallback histórico."
                    ),
                },
            )
        except Exception as e:
            # Falhar aqui não desfaz a cura: o override já está valendo, só a
            # promoção pro código fica pendente.
            logger.warning(f"[evolve] não enfileirei a promoção: {e}")

    def _record_quota(self) -> None:
        try:
            from src.core.use_cases.rate_limiter import RateLimiter

            RateLimiter().record("heal")
        except Exception:
            pass

    def _notify(self, field: str, validation) -> None:
        """Cura silenciosa seria pior que quebra: o dono precisa saber."""
        try:
            import html

            from src.utils.telegram import send_telegram

            send_telegram(
                "🔧 <b>Selector curado</b>\n"
                f"Campo: <code>{html.escape(field)}</code>\n"
                f"Novo: <code>{html.escape(validation.selector)}</code>\n"
                f"Elemento: {html.escape(validation.name or '?')}\n\n"
                "<i>Vale só no banco por enquanto; a promoção pro código vem "
                "pelo drain.</i>",
                topic="alerts",
            )
        except Exception as e:
            logger.warning(f"[evolve] falha ao notificar cura: {e}")


def install(page: Page, *, budget: HealBudget | None = None) -> SelectorHealer | None:
    """Instala o gancho de cura no resolver. ``None`` se desligado."""
    if not enabled():
        return None
    from src.automation.pages.selectors import set_heal_hook

    healer = SelectorHealer(page, budget=budget)
    set_heal_hook(healer)
    logger.info("[evolve] gancho de cura instalado")
    return healer


def uninstall() -> None:
    """Remove o gancho e grava a contabilidade de selectors."""
    from src.automation.pages.selectors import clear_heal_hook, flush_learned

    clear_heal_hook()
    flush_learned()
