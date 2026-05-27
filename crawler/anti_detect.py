import asyncio
import random
from typing import Optional

from config import SEARCH_CONFIG


async def random_delay(
    delay_min: Optional[float] = None,
    delay_max: Optional[float] = None,
) -> float:
    min_value = SEARCH_CONFIG["delay_min"] if delay_min is None else delay_min
    max_value = SEARCH_CONFIG["delay_max"] if delay_max is None else delay_max
    delay = random.uniform(min_value, max_value)
    await asyncio.sleep(delay)
    return delay


async def human_like_scroll(page) -> None:
    total_steps = random.randint(3, 6)
    for step in range(total_steps):
        distance = random.randint(250, 700)
        await page.mouse.move(
            random.randint(50, 900),
            random.randint(50, 700),
            steps=random.randint(8, 20),
        )
        await page.mouse.wheel(0, distance)
        if random.random() < 0.35:
            await asyncio.sleep(random.uniform(0.2, 0.6))
            await page.mouse.wheel(0, -random.randint(60, 180))
        if step != total_steps - 1:
            await asyncio.sleep(random.uniform(0.3, 1.0))


async def human_like_read_pause(
    page,
    *,
    min_pause: float = 0.4,
    max_pause: float = 1.2,
) -> None:
    moves = random.randint(2, 4)
    for _ in range(moves):
        await page.mouse.move(
            random.randint(80, 1200),
            random.randint(80, 760),
            steps=random.randint(10, 25),
        )
        await asyncio.sleep(random.uniform(min_pause, max_pause))


async def human_like_page_settle(page) -> None:
    await asyncio.sleep(random.uniform(1.5, 4.0))
    await human_like_read_pause(page, min_pause=0.6, max_pause=1.6)
    await asyncio.sleep(random.uniform(0.8, 2.0))


def get_user_agent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
