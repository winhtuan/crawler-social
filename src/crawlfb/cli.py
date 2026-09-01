from __future__ import annotations
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context
from crawlfb.intercept import FeedInterceptor, is_reel
from crawlfb.paginate import collect_posts
from crawlfb.comments import (
    CommentInterceptor, collect_comments, expand_comments,
    extract_comments_from_html, switch_to_all_comments, _reel_to_watch,
)
from crawlfb.comment_api import GraphQLForm, fetch_comments, records_from_nodes
from crawlfb.normalize import normalize_post
from crawlfb.writer import write_posts, checkpoint_posts
from crawlfb.models import Comment
from crawlfb.monitor import ResourceMonitor
from crawlfb.recent import existing_post_ids, fetch_recent
from crawlfb.feed_checkpoint import (
    PENDING, DONE, checkpoint_path, build_records, save as save_checkpoint,
    load as load_checkpoint,
)


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
    p.add_argument("--res-interval", type=float, default=15.0,
                   help="seconds between CPU/RAM log lines (0 disables)")
    p.add_argument("--proxy-rotate-minutes", type=float, default=22.0,
                   help="rotate proxy after this many minutes mid-run (0 disables)")
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
                                cfg: Config, form_capture: GraphQLForm) -> list[dict]:
    """Scrape one post's comments, retrying a failed load before skipping — a
    deleted or private post must not sink the run.

    Once the session form is captured (the first permalink nav fires the comment
    root query), comments are fetched by replaying the comment GraphQL queries
    in-page — no per-post goto/scroll. The reverse-engineered commentsIntentToken
    already selects 'All comments', so the sort switch is skipped too. The
    permalink + scroll path stays as the fallback: it bootstraps the form on the
    first post and rescues any post whose fetch fails.

    The whole phase is wrapped so a page crash, a closed page, or a failing
    evaluate on one post degrades to 'no comments for this post' instead of
    aborting the run."""
    if not post_id or not post_url:
        return []
    if form_capture.form is not None:
        try:
            nodes = await fetch_comments(page, form_capture.form, post_id)
            return records_from_nodes(nodes, post_url, cfg.max_comments)
        except Exception as exc:
            print(f"    warn {post_url}: graphql fetch failed ({exc}); falling back")
    # A reel permalink (/reel/<id>/) serves no comments; open the watch URL so
    # the comment section renders. comment_urls below still point at the
    # canonical post_url.
    scrape_url = _reel_to_watch(post_url)
    for attempt in range(3):
        try:
            await page.goto(scrape_url, wait_until="domcontentloaded", timeout=60000)
            break
        except Exception:
            if attempt == 2:
                print(f"    skip {post_url} (failed to load)")
                return []
            await asyncio.sleep(2 * (attempt + 1))
    # A permalink serves its comments in SSR HTML (data-sjs JSON), not in the
    # /api/graphql/ responses — those only carry total_count. Pull them from the
    # page markup; each comment's Relay id buckets it back to this post.
    try:
        interceptor.add_nodes(extract_comments_from_html(await page.content()))
        # The permalink defaults to 'Most relevant', hiding low-relevance comments.
        # Switch to 'All comments' before expanding so they load too.
        await switch_to_all_comments(page)
        await asyncio.sleep(1.0)
        await _expand_post_comments(page, interceptor, post_id, cfg)
    except Exception as exc:
        print(f"    warn {post_url}: comment scrape failed ({exc}); keeping partial")
    try:
        return collect_comments(interceptor, post_url, post_id, cfg.max_comments)
    except Exception as exc:
        print(f"    warn {post_url}: collect_comments failed ({exc})")
        return []


async def _log_resources(monitor: ResourceMonitor, interval: float) -> None:
    """Log CPU/RAM every `interval` seconds until cancelled."""
    while True:
        await asyncio.sleep(interval)
        print(f"  [res] {monitor.line()}")


def _rotate_proxy_script() -> Path:
    """Absolute path to tools/rotate_proxy.py — three levels up from
    src/crawlfb/cli.py (src/crawlfb -> src -> repo root)."""
    return Path(__file__).resolve().parent.parent.parent / "tools" / "rotate_proxy.py"


def _run_rotate_proxy() -> None:
    """Rotate the KiotProxy by running tools/rotate_proxy.py, which writes the
    fresh HTTP_PROXY into .env. The running browser keeps the proxy it launched
    with, so run() relaunches after rotating."""
    subprocess.run([sys.executable, str(_rotate_proxy_script())], check=False)


def _reload_proxy() -> Proxy | None:
    """Re-read HTTP_PROXY from .env after a rotation. rotate_proxy.py rewrote
    .env with the fresh proxy; the crawl loaded .env once at startup, so force a
    re-load and re-parse. Returns None when .env has no HTTP_PROXY."""
    load_dotenv(override=True)
    return Proxy.from_url(os.getenv("HTTP_PROXY"))


async def _crawl_session(
    cfg: Config,
    page_name: str,
    output: Path,
    written_ids: set[str],
    checkpoint: Path,
    resume: bool,
) -> tuple[int, bool, int]:
    """One browser session with the current proxy: Phase 1 (feed scroll) ->
    Phase 2 (comments) -> Phase 3 (API backfill).

    Returns (posts_written, all_done, feed_count). Posts already in
    `written_ids` are skipped, so a relaunched session resumes where the last
    one stopped. Returns all_done=False when the rotation deadline was reached
    with posts still pending, so run() relaunches with a fresh proxy and
    continues. On interrupt/exception, unwritten Phase-1 posts are flushed as
    empty-comment records (best effort) before the exception propagates.

    `resume` skips the Phase 1 feed scroll entirely: the post list (with
    crawl_status) is already in `checkpoint`, so a relaunched session goes
    straight to scraping the posts still marked pending."""
    # A fixed --proxy (not from .env) never rotates, so there's no deadline to
    # relaunch for — one session runs to completion.
    rotate_seconds = cfg.proxy_rotate_minutes * 60 if cfg.proxy_from_env else 0
    session_start = time.monotonic()
    added = 0
    interceptor = None
    completed = False
    try:
        async with launch_context(cfg) as (_ctx, page):
            # Phase 1 — posts only. No comment interceptor and no inline expansion:
            # comment clicks during the scroll starved post collection and tripped
            # Facebook's anti-bot (see docs/adr/0001-two-pass-crawl.md). On resume
            # the feed list is already persisted, so this scroll is skipped.
            if resume:
                raw_posts = load_checkpoint(checkpoint)
            else:
                raw_posts = []
            if not raw_posts:
                interceptor = FeedInterceptor(page, page_name=page_name)
                interceptor.attach()
                posts_url = cfg.normalized_page_url() + "posts/"
                await page.goto(posts_url, wait_until="domcontentloaded", timeout=60000)
                await _trigger_feed(page)
                raw_posts = build_records(await collect_posts(page, interceptor, cfg))
                # The feed interceptor has no role after Phase 1 — detach it so it
                # stops appending Story nodes during Phase 2/3 comment navigation.
                interceptor.detach()
                save_checkpoint(raw_posts, checkpoint)
            collected = len(raw_posts)
            print(f"  {'resumed' if resume else 'collected'} {collected} posts")

            # Phase 2 — comments, one post at a time from its permalink, where the
            # comment section isn't virtualized away. Written incrementally so a
            # crash mid-pass keeps the posts already scraped. Break at the rotation
            # deadline so the session relaunches with a fresh proxy and continues.
            comment_interceptor = CommentInterceptor(page)
            comment_interceptor.attach()
            # Captures the session's /api/graphql/ form envelope from the first
            # comment root query (fired by the first permalink nav in Phase 2) so
            # later posts can replay comment queries without navigating.
            form_capture = GraphQLForm()
            form_capture.attach(page)
            timed_out = False
            for raw in raw_posts:
                post_id = raw.get("post_id") or ""
                if raw.get("crawl_status") == DONE:
                    continue
                if post_id and post_id in written_ids:
                    # Written by an earlier session (or a crash flush) — mark it
                    # done in the checkpoint so a later resume skips it too.
                    raw["crawl_status"] = DONE
                    continue
                if rotate_seconds > 0 and (time.monotonic() - session_start) >= rotate_seconds:
                    timed_out = True
                    break
                post_url = raw.get("permalink_url") or ""
                comments = await _scrape_post_comments(
                    page, comment_interceptor, post_url, post_id, cfg, form_capture)
                result = normalize_post(raw, page_name, comments)
                added += write_posts([result], output)
                written_ids.add(post_id)
                raw["crawl_status"] = DONE
                save_checkpoint(raw_posts, checkpoint)
                # Log only the scraped count. The feed's comment_count (total_count)
                # is unreliable — it undercounts replies and overcounts deleted/spam/
                # blocked-user comments — so printing N/M falsely implies M is the
                # authoritative total. The raw count is still written to each post's
                # "comments" field in the output JSON.
                print(f"  {post_id}: {len(comments)} comments")

            # Phase 3 — fetch the ~3 newest posts from an external API
            # (scrapecreators -> apify) and merge only the ones the feed missed.
            # New posts get the same comment crawl as a feed post; duplicates are
            # skipped (the crawl's copy is richer than the API's). Runs only when
            # Phase 2 completed this session — a timed-out session returns early
            # and the next session picks the remainder up.
            if not timed_out:
                recent_posts = await asyncio.to_thread(fetch_recent, cfg.page_url)
                if recent_posts:
                    new_posts = [p for p in recent_posts if p.post_id and p.post_id not in written_ids]
                    for post in new_posts:
                        comments = await _scrape_post_comments(
                            page, comment_interceptor,
                            post.facebook_url or "", post.post_id or "", cfg, form_capture)
                        post.comments_list = [Comment(**c) for c in comments]
                        added += write_posts([post], output)
                        written_ids.add(post.post_id)
                        print(f"  [recent] {post.post_id}: {len(comments)} comments")

            completed = True
            return added, not timed_out, collected
    finally:
        # An interrupt mid-Phase-1 leaves posts in the interceptor but nothing on
        # disk. Flush whatever hasn't been written yet (as empty-comment records)
        # so a partial crawl still lands on disk and S3. Phase 2/3 posts already
        # written are in written_ids and skipped. Reels are excluded — their
        # comments live in a drawer (docs/adr/0002-exclude-reels.md).
        # This runs only on crash/interrupt: a clean rotation (timed_out) or
        # completion returns normally, and flushing then would write the pending
        # posts as empty-comment so the next session skips their comments.
        if not completed and interceptor is not None:
            try:
                # Cap like Phase 1 did: the final GraphQL batch can overshoot
                # max_posts, and those overflow posts never entered Phase 2, so
                # without the cap they'd flush as bogus empty-comment records.
                raw = [p for p in interceptor.posts if not is_reel(p)][:cfg.max_posts]
                checkpoint_posts(raw, page_name, output, written_ids)
            except Exception as exc:
                print(f"    warn: checkpoint flush failed ({exc})")


async def run(cfg: Config) -> None:
    added = 0
    collected = 0
    page_name = _page_id(cfg.page_url)
    output = Path(cfg.output)
    checkpoint = checkpoint_path(output)
    # Resume across both process restarts (the output file already has posts)
    # and mid-run proxy rotations (posts written by an earlier session).
    written_ids = set(existing_post_ids(output))
    monitor = ResourceMonitor()
    log_task = (
        asyncio.create_task(_log_resources(monitor, cfg.res_interval))
        if cfg.res_interval > 0
        else None
    )

    session = 0
    done = False
    try:
        while not done:
            session += 1
            if session > 1 and cfg.proxy_from_env:
                # The previous session's proxy is about to expire (KiotProxy ~30
                # min lifetime). Rotate to a fresh one and relaunch the browser
                # with it before continuing.
                await asyncio.to_thread(_run_rotate_proxy)
                cfg.proxy = _reload_proxy()
            print(f"== session {session} (proxy: {cfg.proxy.server if cfg.proxy else 'none'})")
            session_added, done, session_collected = await _crawl_session(
                cfg, page_name, output, written_ids, checkpoint, resume=(session > 1))
            added += session_added
            collected = max(collected, session_collected)
    finally:
        if log_task is not None:
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

    # Crawl finished cleanly — the feed checkpoint is a resume artifact only, so
    # drop it once every post is scraped. Kept on interrupt so a re-run resumes.
    if done:
        try:
            checkpoint.unlink(missing_ok=True)
        except OSError:
            pass

    print(f"collected {collected}, wrote {added} new -> {cfg.output}")
    print(f"  [res] final {monitor.line()}")


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
            proxy=Proxy.from_url(args.proxy or os.getenv("HTTP_PROXY")),
            delay_base=args.delay_base,
            delay_jitter=args.delay_jitter,
            storage_state=args.storage_state or os.getenv("FB_STORAGE_STATE"),
            res_interval=args.res_interval,
            proxy_rotate_minutes=args.proxy_rotate_minutes,
            proxy_from_env=args.proxy is None,
        )
        print(f"\n== crawling {url} -> {cfg.output}")
        try:
            asyncio.run(run(cfg))
        except KeyboardInterrupt:
            print(f"interrupted — partial output saved to {cfg.output}")
            break


if __name__ == "__main__":
    main()
