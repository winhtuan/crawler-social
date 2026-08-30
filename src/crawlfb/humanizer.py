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

    def scroll_steps(self, distance: int) -> list[int]:
        """Break one scroll into several human-like increments."""
        steps = []
        remaining = distance
        while remaining > 0:
            step = self.rng.randint(120, 600)
            step = min(step, remaining)
            steps.append(step)
            remaining -= step
        return steps

    async def human_scroll(self, page, distance: int) -> None:
        for step in self.scroll_steps(distance):
            await page.mouse.wheel(0, step)
            await asyncio.sleep(self.rng.uniform(0.2, 0.7))
        await self.pause()
