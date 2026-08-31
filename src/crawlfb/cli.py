from __future__ import annotations
import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context
from crawlfb.intercept import FeedInterceptor
from crawlfb.paginate import collect_posts
from crawlfb.comments import (
    CommentInterceptor, collect_comments, expand_comments,
    extract_comments_from_html, switch_to_all_comments,
)
from crawlfb.normalize import normalize_post
from crawlfb.writer import write_posts


def _page_id(url: str) -> str:
    """Page id from a URL: the last segment after / (trailing slash stripped)."""
    return url.rstrip("/").rsplit("/", 1)[-1] or "page"


def _load_pages(path: str | Path) -> list[tuple[str, str]]:
    """Read a page list from a JSON file, returning [(id, url)].

    Accepts either shape: {"pages": [...]} or a bare array [...].
    Each item is a URL string, or an object {"id": str, "url": str}.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("pages", [])
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            out.append((_page_id(item), item))
        elif isinstance(item, dict) and item.get("url"):
            pid = str(item.get("id") or _page_id(item["url"]))
            out.append((pid, item["url"]))
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl public Facebook page posts")
    p.add_argument("--page", default=None,
                   help="single public page URL (bỏ qua --pages-file)")
    p.add_argument("--pages-file", default="data/fb_pages.json",
                   help="JSON list of pages to crawl (default data/fb_pages.json)")
    p.add_argument("--output", default="output",
                   help="output directory; mỗi page ghi output/{id}.json")
    p.add_argument("--max-posts", type=int, default=50)
    p.add_argument("--max-comments", type=int, default=200,
                   help="max comments per post (default 200; 0 = no cap)")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headed", dest="headless", action="store_false",
                   help="run a visible browser (debug/anti-bot fallback)")
    p.add_argument("--no-humanize", dest="humanize", action="store_false", default=True,
                   help="disable human-like input (faster, less stealthy)")
    p.add_argument("--proxy", default=None, help="http://user:pass@host:port")
    p.add_argument("--delay-base", type=float, default=3.0)
    p.add_argument("--delay-jitter", type=float, default=2.0)
    p.add_argument("--storage-state", default=None)
    return p.parse_args()


async def _trigger_feed(page) -> None:
    """Dismiss any login/consent dialog. The /posts/ feed paginates on scroll
    on its own (logged-in); no reaction flyout / post click needed — those open
    modals that block the scroll loop. Every step is wrapped so a missing
    dialog never crashes the run."""
    for _ in range(2):
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        await asyncio.sleep(0.5)


async def _expand_post_comments(page, interceptor, post_id: str, cfg: Config) -> None:
    """Expand one post's comment section until it reaches cfg.max_comments
    (when a cap is set) or the comment count stops growing. Stale 'view reply'
    buttons keep matching after their reply is loaded, so stop on a count
    plateau rather than on a click-count plateau."""
    target = cfg.max_comments if cfg.max_comments > 0 else 10**18
    stale_streak = 0
    for _ in range(30):
        before = len(interceptor.comments_for_post(post_id))
        if before >= target:
            return
        await expand_comments(page, cfg, rounds=1)
        after = len(interceptor.comments_for_post(post_id))
        if after == before:
            stale_streak += 1
            if stale_streak >= 3:
                return
        else:
            stale_streak = 0


async def _scrape_post_comments(page, interceptor, post_url: str, post_id: str,
                                cfg: Config) -> list[dict]:
    """Open a post's permalink and scrape its comments, retrying a failed load
    twice before skipping — a deleted or private post must not sink the run."""
    if not post_url:
        return []
    for attempt in range(3):
        try:
            await page.goto(post_url, wait_until="domcontentloaded", timeout=60000)
            break
        except Exception:
            if attempt == 2:
                print(f"    skip {post_url} (failed to load)")
                return []
            await asyncio.sleep(2 * (attempt + 1))
    # A permalink serves its comments in SSR HTML (data-sjs JSON), not in the
    # /api/graphql/ responses — those only carry total_count. Pull them from the
    # page markup; each comment's Relay id buckets it back to this post.
    interceptor.add_nodes(extract_comments_from_html(await page.content()))
    # The permalink defaults to 'Most relevant', hiding low-relevance comments.
    # Switch to 'All comments' before expanding so they load too.
    await switch_to_all_comments(page)
    await asyncio.sleep(1.0)
    await _expand_post_comments(page, interceptor, post_id, cfg)
    return collect_comments(interceptor, post_url, post_id, cfg.max_comments)


async def run(cfg: Config) -> None:
    added = 0
    collected = 0
    async with launch_context(cfg) as (_ctx, page):
        page_name = _page_id(cfg.page_url)

        # Phase 1 — posts only. No comment interceptor and no inline expansion:
        # comment clicks during the scroll starved post collection and tripped
        # Facebook's anti-bot (see docs/adr/0001-two-pass-crawl.md).
        interceptor = FeedInterceptor(page, page_name=page_name)
        interceptor.attach()
        posts_url = cfg.normalized_page_url() + "posts/"
        await page.goto(posts_url, wait_until="domcontentloaded", timeout=60000)
        await _trigger_feed(page)
        raw_posts = await collect_posts(page, interceptor, cfg)
        collected = len(raw_posts)
        print(f"  collected {collected} posts")

        # Phase 2 — comments, one post at a time from its permalink, where the
        # comment section isn't virtualized away. Written incrementally so a
        # crash mid-pass keeps the posts already scraped.
        comment_interceptor = CommentInterceptor(page)
        comment_interceptor.attach()
        for i, raw in enumerate(raw_posts, 1):
            post_url = raw.get("permalink_url") or ""
            post_id = raw.get("post_id") or ""
            comments = await _scrape_post_comments(
                page, comment_interceptor, post_url, post_id, cfg)
            result = normalize_post(raw, page_name, comments)
            added += write_posts([result], Path(cfg.output))
            # Log only the scraped count. The feed's comment_count (total_count)
            # is unreliable — it undercounts replies and overcounts deleted/spam/
            # blocked-user comments — so printing N/M falsely implies M is the
            # authoritative total. The raw count is still written to each post's
            # "comments" field in the output JSON.
            print(f"  [{i}/{collected}] {post_id}: {len(comments)} comments")

    print(f"collected {collected}, wrote {added} new -> {cfg.output}")


def main() -> None:
    args = parse_args()
    load_dotenv()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.page:
        tasks = [(_page_id(args.page), args.page)]
    else:
        tasks = _load_pages(args.pages_file)

    if not tasks:
        print(f"no pages to crawl (--page empty and {args.pages_file} has none)")
        return

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    for pid, url in tasks:
        cfg = Config(
            page_url=url,
            output=str(output_dir / f"{pid}_{run_id}.json"),
            max_posts=args.max_posts,
            max_comments=args.max_comments,
            headless=args.headless,
            humanize=args.humanize,
            proxy=Proxy.from_url(args.proxy or os.getenv("FB_PROXY")),
            delay_base=args.delay_base,
            delay_jitter=args.delay_jitter,
            storage_state=args.storage_state or os.getenv("FB_STORAGE_STATE"),
        )
        print(f"\n== crawling {url} -> {cfg.output}")
        asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
