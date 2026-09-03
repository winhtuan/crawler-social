from __future__ import annotations
import asyncio
import random


class Humanizer:
    """Randomized pauses and human-like scrolling to avoid bot heuristics."""

    def __init__(self, base: float = 3.0, jitter: float = 2.0,
                 rng: random.Random | None = None):
        self.base = base
        self.jitter = jitter
        self.rng = rng or random.SystemRandom()

    def next_delay(self) -> float:
        return max(0.5, self.base + self.rng.uniform(-self.jitter, self.jitter))

    async def pause(self) -> None:
        await asyncio.sleep(self.next_delay())
