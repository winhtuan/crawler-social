from __future__ import annotations
from crawlfb.config import Config
from crawlfb.humanizer import Humanizer
from crawlfb.intercept import FeedInterceptor, is_reel


def update_stall(count: int, last_count: int, stall: int, stall_limit: int) -> tuple[int, bool]:
    """Advance the stall counter after one scroll pass.

    Returns (new_stall, should_stop). Growth in the non-reel post count resets
    the counter; a pass with no growth increments it and signals stop once it
    reaches stall_limit.
    """
    if count == last_count:
        stall += 1
        return stall, stall >= stall_limit
    return 0, False


async def _wait_for_feed_batch(page, timeout_ms: int = 8000) -> None:
    """Wait for the next GraphQL feed batch to land (bounded).

    Facebook's feed pagination fires a /api/graphql/ request after each scroll,
    but the response can lag the scroll by a few seconds. Waiting for it — instead
    of a blind pause — keeps the stall detector from counting a slow batch as a
    dead feed. The timeout is swallowed: the caller's count check still runs, and
    a truly stalled feed is caught by update_stall.
    """
    try:
        await page.wait_for_response(
            lambda resp: "/api/graphql/" in resp.url,
            timeout=timeout_ms,
        )
    except Exception:
        pass


async def collect_posts(page, interceptor: FeedInterceptor, cfg: Config) -> list[dict]:
    """Scroll the timeline until max_posts non-reel posts collected or the feed
    truly stalls.

    A logged-out FB feed paginates via an intersection sentinel at the page
    bottom; a plain wheel scroll may not reach it. So every iteration jumps
    the window to the bottom (guaranteed to fire the next GraphQL batch) and
    adds a small human-like wheel scroll on top. Each pass then waits for the
    GraphQL batch to actually arrive before checking growth, so a slow batch
    isn't mistaken for a dead feed. We stop early when the count stops growing
    across stall_limit consecutive passes (page ran out of posts), with a hard
    cap so a wedged page can't hang forever.

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
        await _wait_for_feed_batch(page)
        count = len(_posts())
        stall, stop = update_stall(count, last_count, stall, cfg.stall_limit)
        if stop:
            break
        last_count = count
        await human.pause()
    return _posts()[:cfg.max_posts]
