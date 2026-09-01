from __future__ import annotations
import json
from pathlib import Path
from crawlfb.models import Post
from crawlfb.normalize import normalize_post


def _load(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def write_posts(posts: list[Post], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load(path)
    # Upsert by post_id: re-running a crawl refreshes a post's comments rather
    # than keeping the stale first-seen copy, and preserves posts from earlier
    # runs that no longer appear in the feed.
    by_id = {p.get("post_id"): p for p in existing if p.get("post_id")}
    added = 0
    for post in posts:
        if not post.post_id:
            continue
        if post.post_id in by_id:
            by_id[post.post_id] = post.model_dump()
        else:
            by_id[post.post_id] = post.model_dump()
            added += 1
    path.write_text(
        json.dumps(list(by_id.values()), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return added


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
