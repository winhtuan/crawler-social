from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
from crawlfb.config import Config
from crawlfb.stealth import launch_context
from crawlfb.intercept import FeedInterceptor
from crawlfb.paginate import collect_posts
from crawlfb.writer import write_posts


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl public Facebook page posts")
    p.add_argument("--page", required=True, help="public page URL")
    p.add_argument("--output", required=True, help="output JSON path")
    p.add_argument("--max-posts", type=int, default=50)
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headed", dest="headless", action="store_false",
                   help="run a visible browser (debug/anti-bot fallback)")
    p.add_argument("--proxy", default=None, help="http://user:pass@host:port")
    p.add_argument("--delay-base", type=float, default=3.0)
    p.add_argument("--delay-jitter", type=float, default=2.0)
    p.add_argument("--storage-state", default=None)
    return p.parse_args()


async def _trigger_feed(page) -> None:
    """Best-effort interaction to force the logged-out feed's /api/graphql/
    requests to fire. A logged-out Facebook page inlines the feed in HTML and
    emits ZERO /api/graphql/ on passive load or scroll (empirical, Task 3) —
    the feed GraphQL only fires after interaction. This replicates
    tools/capture_feed.py (proven to work). Every step is wrapped so a missing
    selector never crashes the run; the interceptor + scroll loop still run
    even if the trigger fully fails."""
    try:
        await page.wait_for_selector('[role="article"]', timeout=30000)
    except Exception:
        pass
    # Dismiss the login dialog.
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await asyncio.sleep(0.5)
    # Open the reaction-count flyout.
    for label in ("Tất cả cảm xúc", "Bình luận"):
        try:
            el = page.get_by_text(label, exact=False).first
            if await el.count():
                await el.click(timeout=4000, force=True)
                await asyncio.sleep(6)
                break
        except Exception:
            pass
    # Click a post to open the post permalink view.
    try:
        await page.locator('[role="article"]').first.click(timeout=4000, force=True)
        await asyncio.sleep(6)
    except Exception:
        pass


async def run(cfg: Config) -> None:
    async with launch_context(cfg) as (_ctx, page):
        page_name = cfg.page_url.rstrip("/").rsplit("/", 1)[-1]
        interceptor = FeedInterceptor(page, page_name=page_name)
        interceptor.attach()
        await page.goto(cfg.normalized_page_url(), wait_until="networkidle", timeout=60000)
        await _trigger_feed(page)
        posts = await collect_posts(page, interceptor, cfg)
    added = write_posts(posts, Path(cfg.output))
    print(f"collected {len(posts)}, wrote {added} new -> {cfg.output}")


def main() -> None:
    cfg = Config.from_args(parse_args())
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
