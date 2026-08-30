from __future__ import annotations
from crawlfb.config import Config
from crawlfb.humanizer import Humanizer
from crawlfb.intercept import FeedInterceptor, is_reel


async def collect_posts(page, interceptor: FeedInterceptor, cfg: Config) -> list[dict]:
    """Scroll the timeline until max_posts non-reel posts collected or the feed
    truly stalls.

    A logged-out FB feed paginates via an intersection sentinel at the page
    bottom; a plain wheel scroll may not reach it. So every iteration jumps
    the window to the bottom (guaranteed to fire the next GraphQL batch) and
    adds a small human-like wheel scroll on top. We stop early only when the
    count stops growing across stall_limit consecutive scrolls (page ran out
    of posts), with a hard cap so a wedged page can't hang forever.

    Reels are counted out and dropped — their permalink is /reel/ and their
    comments live in a drawer the comment pass can't read (see
    docs/adr/0002-exclude-reels.md)."""
    human = Humanizer(base=cfg.delay_base, jitter=cfg.delay_jitter)
    stall = 0
    last_count = 0
    max_scrolls = max(cfg.max_posts * 5, 100)

    def _posts() -> list[dict]:
        return [p for p in interceptor.posts if not is_reel(p)]

    for _ in range(max_scrolls):
        posts = _posts()
        if len(posts) >= cfg.max_posts:
            break
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.mouse.wheel(0, cfg.scroll_distance)
        await human.pause()
        count = len(_posts())
        if count == last_count:
            stall += 1
            if stall >= cfg.stall_limit:
                break
        else:
            stall = 0
        last_count = count
    return _posts()[:cfg.max_posts]
