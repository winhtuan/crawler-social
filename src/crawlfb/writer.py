from __future__ import annotations
import json
from pathlib import Path
from crawlfb.models import Post


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
