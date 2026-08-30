from __future__ import annotations
from crawlfb.config import Config
from crawlfb.humanizer import Humanizer
from crawlfb.intercept import FeedInterceptor
from crawlfb.models import Post


async def collect_posts(page, interceptor: FeedInterceptor, cfg: Config) -> list[Post]:
    """Scroll the timeline until max_posts collected or the feed stalls."""
    human = Humanizer(base=cfg.delay_base, jitter=cfg.delay_jitter)
    stall = 0
    last_count = 0
    while len(interceptor.posts) < cfg.max_posts:
        await human.human_scroll(page, cfg.scroll_distance)
        count = len(interceptor.posts)
        if count == last_count:
            stall += 1
            if stall >= cfg.stall_limit:
                break
        else:
            stall = 0
        last_count = count
    return interceptor.to_models(cfg.normalized_page_url())
