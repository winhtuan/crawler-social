from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context
from crawlfb.intercept import FeedInterceptor
from crawlfb.paginate import collect_posts
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
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headed", dest="headless", action="store_false",
                   help="run a visible browser (debug/anti-bot fallback)")
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


async def run(cfg: Config) -> None:
    async with launch_context(cfg) as (_ctx, page):
        page_name = cfg.page_url.rstrip("/").rsplit("/", 1)[-1]
        interceptor = FeedInterceptor(page, page_name=page_name)
        interceptor.attach()
        # The page's /posts/ tab is the paginated feed; the base page URL only
        # shows a short recent-posts preview that doesn't infinite-scroll.
        posts_url = cfg.normalized_page_url() + "posts/"
        await page.goto(posts_url, wait_until="networkidle", timeout=60000)
        await _trigger_feed(page)
        posts = await collect_posts(page, interceptor, cfg)
    added = write_posts(posts, Path(cfg.output))
    print(f"collected {len(posts)}, wrote {added} new -> {cfg.output}")


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

    for pid, url in tasks:
        cfg = Config(
            page_url=url,
            output=str(output_dir / f"{pid}.json"),
            max_posts=args.max_posts,
            headless=args.headless,
            proxy=Proxy.from_url(args.proxy or os.getenv("FB_PROXY")),
            delay_base=args.delay_base,
            delay_jitter=args.delay_jitter,
            storage_state=args.storage_state or os.getenv("FB_STORAGE_STATE"),
        )
        print(f"\n== crawling {url} -> {cfg.output}")
        asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
