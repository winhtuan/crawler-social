# Fix crawl-fb Criticals + Isolation Gap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two Critical findings (Ctrl+C during Phase 1 loses all crawled posts; plaintext credential in `todo.md`) and the Important isolation gap (one post's failure aborts the whole crawl) from the code review.

**Architecture:** Add a `checkpoint_posts` helper in `writer.py` that writes raw feed posts as empty-comment records, and flush it from `run()`'s `finally` so a mid-Phase-1 interrupt still persists everything the interceptor collected. Wrap the per-post comment-scrape body in `_scrape_post_comments` so a page crash degrades to "no comments for this post" instead of killing the run.

**Tech Stack:** Python 3.13, asyncio, pydantic v2, pytest.

**Spec:** [docs/code-review-2026-09-01.md](../../code-review-2026-09-01.md) — Critical #1 (Phase-1 checkpoint), Critical #2 (plaintext credential), Important #3 (per-post isolation).

## Global Constraints

- Python 3.13; no new dependencies.
- Tests run with `pytest` from the `crawl-fb` repo root.
- Async tests use `asyncio.run(...)` inside sync `def test_*` functions (no pytest-asyncio required).
- Do NOT print secret values in code, tests, or logs.
- `todo.md` is gitignored — editing it creates no git change; there is nothing to commit for that task.

---

### Task 1: Add `checkpoint_posts` helper

**Files:**
- Modify: `src/crawlfb/writer.py` (add function + import)
- Test: `tests/test_writer.py` (add tests)

**Interfaces:**
- Produces: `checkpoint_posts(raw_posts: list[dict], page_name: str, output_path: Path, written_ids: set[str] | None = None) -> set[str]` — writes the not-yet-written raw posts as empty-comment `Post` records via `write_posts`, returns the updated `written_ids`. Task 2 consumes it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_writer.py`:

```python
import json
from pathlib import Path
from crawlfb.models import Post
from crawlfb.writer import write_posts, checkpoint_posts


def _raw(pid: str) -> dict:
    return {"post_id": pid, "permalink_url": f"https://fb.com/{pid}", "text": "hi"}


def test_checkpoint_posts_writes_empty_comment_records(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([_raw("1"), _raw("2")], "p", out)
    assert written == {"1", "2"}
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["post_id"] for p in data] == ["1", "2"]
    assert all(p["comments_list"] == [] for p in data)


def test_checkpoint_posts_skips_already_written_ids(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([_raw("1")], "p", out)
    written = checkpoint_posts([_raw("1"), _raw("2")], "p", out, written_ids=written)
    assert written == {"1", "2"}
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["post_id"] for p in data] == ["1", "2"]


def test_checkpoint_posts_skips_posts_without_id(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([{"text": "no id"}], "p", out)
    assert written == set()
    assert not out.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_writer.py -v`
Expected: FAIL — `ImportError: cannot import name 'checkpoint_posts' from 'crawlfb.writer'`

- [ ] **Step 3: Write minimal implementation**

In `src/crawlfb/writer.py`, change the imports and add the function:

```python
from crawlfb.models import Post
from crawlfb.normalize import normalize_post
```

```python
def checkpoint_posts(raw_posts: list[dict], page_name: str, output_path: Path,
                     written_ids: set[str] | None = None) -> set[str]:
    """Write the raw feed posts that haven't been written yet, as empty-comment
    records, and return the updated set of written post_ids.

    Phase 1 collects posts in memory only; on Ctrl+C mid-scroll the interceptor
    holds every post seen so far but nothing is on disk. run() flushes those raw
    posts through this in its finally so a partial crawl still lands on disk/S3.
    Phase 2 later enriches each post with comments via write_posts (upsert by
    post_id), which replaces the empty-comment record.
    """
    written = set(written_ids) if written_ids is not None else set()
    posts = [
        normalize_post(raw, page_name, [])
        for raw in raw_posts
        if raw.get("post_id") and raw.get("post_id") not in written
    ]
    if posts:
        write_posts(posts, Path(output_path))
        written.update(p.post_id for p in posts)
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_writer.py -v`
Expected: PASS (3 new tests + existing `test_write_posts_*`)

- [ ] **Step 5: Commit**

```bash
git add src/crawlfb/writer.py tests/test_writer.py
git commit -m "feat(crawl-fb): add checkpoint_posts for mid-crawl crash safety"
```

---

### Task 2: Flush interceptor posts in `run()`'s `finally`

**Files:**
- Modify: `src/crawlfb/cli.py` (imports + `run()` body)

**Interfaces:**
- Consumes: `checkpoint_posts` (Task 1), `is_reel` (from `crawlfb.intercept`).
- Produces: no new public symbol. Behavior change only.

**Note on testing:** This is integration wiring over a live Playwright browser; there is no clean unit seam. Verify with the existing suite plus a manual Ctrl+C smoke test (Step 5). The pure behavior it depends on (`checkpoint_posts`, `is_reel`) is already covered by Task 1 and existing tests.

- [ ] **Step 1: Update imports**

In `src/crawlfb/cli.py`, change:

```python
from crawlfb.intercept import FeedInterceptor
```

to:

```python
from crawlfb.intercept import FeedInterceptor, is_reel
```

and:

```python
from crawlfb.writer import write_posts
```

to:

```python
from crawlfb.writer import write_posts, checkpoint_posts
```

- [ ] **Step 2: Hoist state and add the finally-flush in `run()`**

In `src/crawlfb/cli.py`, rewrite the `run()` function body as follows. Keep the Phase 1/2/3 comments and logic identical except for the additions marked below.

```python
async def run(cfg: Config) -> None:
    added = 0
    collected = 0
    written_ids: set[str] = set()
    interceptor = None
    page_name = None
    monitor = ResourceMonitor()
    log_task = (
        asyncio.create_task(_log_resources(monitor, cfg.res_interval))
        if cfg.res_interval > 0
        else None
    )
    try:
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
                written_ids.add(post_id)
                # Log only the scraped count. The feed's comment_count (total_count)
                # is unreliable — it undercounts replies and overcounts deleted/spam/
                # blocked-user comments — so printing N/M falsely implies M is the
                # authoritative total. The raw count is still written to each post's
                # "comments" field in the output JSON.
                print(f"  [{i}/{collected}] {post_id}: {len(comments)} comments")

            # Phase 3 — fetch the ~3 newest posts from an external API
            # (scrapecreators -> apify) and merge only the ones the feed missed.
            # New posts get the same comment crawl as a feed post; duplicates are
            # skipped (the crawl's copy is richer than the API's).
            recent_posts = await asyncio.to_thread(fetch_recent, cfg.page_url)
            if recent_posts:
                seen = existing_post_ids(Path(cfg.output))
                new_posts = [p for p in recent_posts if p.post_id and p.post_id not in seen]
                for j, post in enumerate(new_posts, 1):
                    comments = await _scrape_post_comments(
                        page, comment_interceptor,
                        post.facebook_url or "", post.post_id or "", cfg)
                    post.comments_list = [Comment(**c) for c in comments]
                    added += write_posts([post], Path(cfg.output))
                    written_ids.add(post.post_id)
                    print(f"  [recent {j}/{len(new_posts)}] {post.post_id}: {len(comments)} comments")
    finally:
        # An interrupt mid-Phase-1 leaves posts in the interceptor but nothing on
        # disk. Flush whatever hasn't been written yet (as empty-comment records)
        # so a partial crawl still lands on disk and S3. Phase 2/3 posts already
        # written are in written_ids and skipped. Reels are excluded — their
        # comments live in a drawer (docs/adr/0002-exclude-reels.md).
        if interceptor is not None and page_name is not None:
            try:
                raw = [p for p in interceptor.posts if not is_reel(p)]
                checkpoint_posts(raw, page_name, Path(cfg.output), written_ids)
            except Exception:
                pass
        if log_task is not None:
            log_task.cancel()
            try:
                await log_task
            except asyncio.CancelledError:
                pass

    print(f"collected {collected}, wrote {added} new -> {cfg.output}")
    print(f"  [res] final {monitor.line()}")
```

- [ ] **Step 3: Run the full test suite**

Run: `pytest -q`
Expected: PASS — all existing tests still green (the `run()` wiring has no unit test; existing `test_cli.py` import of `cli` must still succeed, confirming the `is_reel`/`checkpoint_posts` imports resolve).

- [ ] **Step 4: Manual Ctrl+C smoke test**

Run: `python -m crawlfb.cli --page "https://www.facebook.com/<some-public-page>" --max-posts 20 --headed`
Press Ctrl+C during the Phase 1 scroll (before the "collected N posts" line). Verify:
- The process prints `interrupted — partial output saved to ...`.
- The output file (`output/<id>_<run_id>.json`) exists and contains the posts collected before the interrupt, each with an empty `comments_list`.

- [ ] **Step 5: Commit**

```bash
git add src/crawlfb/cli.py
git commit -m "fix(crawl-fb): persist Phase-1 posts on Ctrl+C via finally-flush"
```

---

### Task 3: Remove plaintext credential from `todo.md`

**Files:**
- Modify: `todo.md` (remove the last two lines)

**Note:** `todo.md` is gitignored, so this edit produces no git change and needs no commit. The password rotation in Step 4 is a human action and cannot be automated here.

- [ ] **Step 1: Remove the credential lines**

Delete these two lines from `todo.md` (the email and the password that follow the roadmap list):

```
<redacted email>
<redacted password>
```

Keep the roadmap bullet list above them.

- [ ] **Step 2: Verify the credential is gone from the working tree**

Run: `grep -RInE '<email from todo.md>|<password from todo.md>' . --exclude-dir=.git --exclude-dir=.pytest_cache --exclude-dir=__pycache__` (substitute the actual values being removed; do not paste them into any committed file)
Expected: no matches.

- [ ] **Step 3: Rotate the password (human, manual)**

The password was exposed in a local working-tree file. Log in to the account named in `todo.md` and change its password. Do NOT reuse the leaked value.

- [ ] **Step 4: (No commit — todo.md is gitignored)**

---

### Task 4: Isolate per-post comment-scrape failures

**Files:**
- Modify: `src/crawlfb/cli.py` (`_scrape_post_comments`)
- Test: `tests/test_cli.py` (add async tests with fake pages)

**Interfaces:**
- Consumes: `CommentInterceptor`, `extract_comments_from_html`, `switch_to_all_comments`, `_expand_post_comments`, `collect_comments`, `_reel_to_watch` (all already imported/available in `cli.py`).
- Produces: unchanged signature `_scrape_post_comments(page, interceptor, post_url, post_id, cfg) -> list[dict]`; it now never raises on a per-post failure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
import asyncio
from crawlfb.cli import _scrape_post_comments
from crawlfb.comments import CommentInterceptor
from crawlfb.config import Config


class _GotoOkPage:
    async def goto(self, *a, **k):
        return None

    async def content(self):
        raise RuntimeError("page closed")


class _EvalBoomPage:
    async def goto(self, *a, **k):
        return None

    async def content(self):
        return "<html></html>"

    async def evaluate(self, *a, **k):
        raise RuntimeError("context destroyed")


def _cfg() -> Config:
    return Config(page_url="https://www.facebook.com/p", output="out.json")


def test_scrape_post_comments_survives_page_content_crash():
    page = _GotoOkPage()
    interceptor = CommentInterceptor(page)
    comments = asyncio.run(_scrape_post_comments(
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg()))
    assert comments == []


def test_scrape_post_comments_survives_evaluate_crash():
    page = _EvalBoomPage()
    interceptor = CommentInterceptor(page)
    comments = asyncio.run(_scrape_post_comments(
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg()))
    assert comments == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL — `test_scrape_post_comments_survives_page_content_crash` raises `RuntimeError("page closed")` (uncaught) instead of returning `[]`.

- [ ] **Step 3: Write minimal implementation**

In `src/crawlfb/cli.py`, replace the body of `_scrape_post_comments` after the goto-retry loop with a wrapped version. The whole function becomes:

```python
async def _scrape_post_comments(page, interceptor, post_url: str, post_id: str,
                                cfg: Config) -> list[dict]:
    """Open a post's permalink and scrape its comments, retrying a failed load
    twice before skipping — a deleted or private post must not sink the run.

    The comment-scrape phase (parse + expand + collect) is wrapped so a page
    crash, a closed page, or a failing evaluate on one post degrades to 'no
    comments for this post' instead of aborting the whole run."""
    if not post_url:
        return []
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS — both new tests return `[]` without raising, plus the existing `_load_pages`/`_page_id` tests.

- [ ] **Step 5: Commit**

```bash
git add src/crawlfb/cli.py tests/test_cli.py
git commit -m "fix(crawl-fb): isolate per-post comment failures so one post can't abort the run"
```

---

## Self-Review

- **Spec coverage:** Critical #1 → Task 1 (helper) + Task 2 (wiring). Critical #2 → Task 3. Important #3 → Task 4. All three review findings addressed.
- **Placeholder scan:** no TBD/TODO/placeholders; every step has concrete code or an exact command.
- **Type consistency:** `checkpoint_posts` signature matches between Task 1 (definition) and Task 2 (call site: `checkpoint_posts(raw, page_name, Path(cfg.output), written_ids)`). `written_ids` is a `set[str]` throughout. `_scrape_post_comments` signature unchanged.
