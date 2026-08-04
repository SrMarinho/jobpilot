"""Ritmo humano: pausas e digitação com variação aleatória.

Ação automatizada em cadência constante é um dos sinais mais fáceis de detectar
— um humano não clica exatamente a cada 2,0 segundos. O projeto tinha pausa
randomizada em só dois lugares (e num deles apenas na primeira página); o resto
eram ~60 `wait_for_timeout` de valor fixo, e três faixas diferentes de delay de
digitação, cada uma escolhida no olho.

Aqui as faixas viram perfis nomeados, ajustáveis por env sem tocar no código.

Não substitui espera de carregamento — para "aguardar a página responder" use
`wait_for_selector`/`first_visible`, que terminam assim que o elemento aparece.
Este módulo é para o intervalo *entre ações*, onde a demora é o objetivo.
"""

import asyncio
import random
from dataclasses import dataclass

from src.config.env import env_str
from src.config.settings import logger


@dataclass(frozen=True, slots=True)
class PacingProfile:
    """Faixas em segundos (pausas) e milissegundos (digitação)."""

    name: str
    pause: tuple[float, float]
    short_pause: tuple[float, float]
    typing_ms: tuple[int, int]


PROFILES: dict[str, PacingProfile] = {
    # Sessão manual, quando você está olhando e quer velocidade.
    "fast": PacingProfile("fast", (1.5, 3.5), (0.4, 1.0), (8, 25)),
    # Padrão dos runs agendados.
    "normal": PacingProfile("normal", (4.0, 10.0), (1.0, 2.5), (20, 60)),
    # Conta que já levou checkpoint, ou volume alto no dia.
    "cautious": PacingProfile("cautious", (10.0, 25.0), (2.0, 5.0), (45, 110)),
}
DEFAULT_PROFILE = "normal"


def current_profile() -> PacingProfile:
    """Perfil ativo, de ``PACING_PROFILE``."""
    name = env_str("PACING_PROFILE", DEFAULT_PROFILE).lower()
    profile = PROFILES.get(name)
    if profile is None:
        logger.warning(
            f"PACING_PROFILE={name!r} desconhecido — usando {DEFAULT_PROFILE}"
        )
        return PROFILES[DEFAULT_PROFILE]
    return profile


def _seconds(faixa: tuple[float, float]) -> float:
    # uniform e não randint: valor fracionário não cai numa grade de 1s.
    return random.uniform(*faixa)


async def human_pause(profile: PacingProfile | None = None) -> None:
    """Pausa entre duas ações — o intervalo típico entre cliques."""
    await asyncio.sleep(_seconds((profile or current_profile()).pause))


async def short_pause(profile: PacingProfile | None = None) -> None:
    """Pausa curta — entre passos de uma mesma ação (abrir menu → clicar)."""
    await asyncio.sleep(_seconds((profile or current_profile()).short_pause))


def typing_delay(profile: PacingProfile | None = None) -> int:
    """Delay por tecla (ms) pro ``type()`` do Playwright."""
    return random.randint(*(profile or current_profile()).typing_ms)


async def type_like_human(
    locator, text: str, profile: PacingProfile | None = None
) -> None:
    """Digita com cadência humana no locator dado."""
    await locator.type(text, delay=typing_delay(profile))
