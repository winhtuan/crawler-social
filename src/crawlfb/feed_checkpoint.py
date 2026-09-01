"""Persist the Phase-1 feed post list so a proxy-rotation relaunch can resume
comment scraping without re-scrolling the feed.

The checkpoint is a JSON list, one object per feed post: the raw feed record
plus a `crawl_status` key ("pending" -> "done"). It is written after Phase 1
and updated in place as each post's comments are scraped. The raw record is
kept because normalize_post needs the feed metadata (text, author, reactions,
attachments) after a relaunch — post_id and permalink_url alone aren't enough.

Stored beside the output file with a `.feed.json` suffix so run.py's S3 upload
(which globs `*.json`) can skip it.
"""
from __future__ import annotations

import json
from pathlib import Path

PENDING = "pending"
DONE = "done"


def checkpoint_path(output: Path) -> Path:
    """Feed checkpoint path: the output file's sibling, `.json` -> `.feed.json`."""
    return output.with_suffix(".feed.json")


def build_records(raw_posts: list[dict]) -> list[dict]:
    """Add a `crawl_status = "pending"` field to each raw feed record."""
    return [{**raw, "crawl_status": PENDING} for raw in raw_posts]


def save(records: list[dict], path: Path) -> None:
    """Write the current records (with their crawl_status) to the checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load(path: Path) -> list[dict]:
    """Read the checkpoint records, or [] when missing or corrupt."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []
    return data if isinstance(data, list) else []
