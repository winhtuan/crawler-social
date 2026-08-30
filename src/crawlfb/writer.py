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
    seen = {p.get("postId") for p in existing if p.get("postId")}
    added = 0
    for post in posts:
        if post.postId and post.postId not in seen:
            existing.append(post.model_dump())
            seen.add(post.postId)
            added += 1
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return added
