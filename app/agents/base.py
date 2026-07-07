"""Базовый интерфейс AI-агента.

Все агенты (сегментация, обогащение, кампании) реализуют один интерфейс.
Движок сейчас — OpenRouter (DeepSeek). В будущем сюда можно подставить
Hermes-agent, не меняя вызывающий код.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """Вход агента: доменные данные + произвольные параметры."""

    payload: Any = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Выход агента: результат + метаданные (уверенность, обоснование)."""

    data: Any = None
    confidence: float | None = None
    reasoning: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Agent(ABC):
    name: str = "agent"

    @property
    def available(self) -> bool:
        return True

    @abstractmethod
    async def run(self, context: AgentContext) -> AgentResult:
        ...
