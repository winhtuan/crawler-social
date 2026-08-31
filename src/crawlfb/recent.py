"""Fetch the ~3 most recent posts from an external API and merge them into a
crawl output file, deduped by post_id.

Primary source is Scrape Creators (scrapecreators.com). When it fails (network
error, `success: false`, or a missing `posts` key), we retry once (two attempts
total) and then fall back to the Apify facebook-posts-scraper actor.

Only post records are merged — neither API returns full comment threads, only
counts and (for scrapecreators) top comments. So a merge adds new posts but
never clobbers the richer internal post that the crawl already wrote.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from crawlfb.models import Attachment, Post, TopComment
from crawlfb.normalize import _hashtags

_SCRAPE_BASE = "https://api.scrapecreators.com"
_APIFY_ACTOR = "apify~facebook-posts-scraper"

# apify reaction-count field -> lowercase reaction key used in the output.
_REACTION_FIELDS = {
    "like": "reactionLikeCount",
    "love": "reactionLoveCount",
    "care": "reactionCareCount",
    "wow": "reactionWowCount",
    "haha": "reactionHahaCount",
}


def _http_json(
    url: str,
    *,
    headers: dict | None = None,
    method: str = "GET",
    body: dict | None = None,
    timeout: int = 60,
) -> dict | list:
    """GET/POST a JSON endpoint and return the parsed body (dict or list).

    Raises on any HTTP/network error — the caller decides the retry/fallback."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _iso_from_unix(ts: int) -> str:
    """Unix seconds -> ISO-8601 with milliseconds and a Z suffix.

    Mirrors the `created_time_iso` format produced by the feed interceptor, so
    timestamps stay comparable after a merge."""
    if not ts:
        return ""
    try:
        return (
            datetime.fromtimestamp(ts, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    except (ValueError, OSError):
        return ""


def _normalize_scrapecreators(p: dict, page_name: str) -> Post:
    """Map one scrapecreators `posts[]` item to the internal Post model."""
    video = p.get("videoDetails") or {}
    is_video = bool(video)
    attachments = []
    if is_video:
        attachments.append(
            Attachment(
                thumbnail=video.get("thumbnailUrl"),
                url=video.get("hdUrl") or video.get("sdUrl"),
                type="Video",
            )
        )
    top_comments = [
        TopComment(
            text=c.get("text") or "",
            author=(c.get("author") or {}).get("name") or "",
        )
        for c in (p.get("topComments") or [])
    ]
    text = p.get("text") or ""
    return Post(
        post_id=str(p.get("id") or ""),
        facebook_url=p.get("permalink") or p.get("url"),
        text=text,
        author=(p.get("author") or {}).get("name"),
        page_name=page_name,
        timestamp=_iso_from_unix(int(p.get("publishTime") or 0)),
        likes=int(p.get("reactionCount") or 0),
        comments=int(p.get("commentCount") or 0),
        top_comments=top_comments,
        is_video=is_video,
        views=int(p.get("videoViewCount") or 0),
        hashtags=_hashtags(text),
        attachments=attachments,
    )


def _normalize_apify(p: dict, page_name: str) -> Post:
    """Map one Apify facebook-posts-scraper dataset item to the Post model."""
    text = p.get("text") or ""
    reactions: dict[str, int] = {}
    for key, field in _REACTION_FIELDS.items():
        n = int(p.get(field) or 0)
        if n > 0:
            reactions[key] = n
    media = p.get("media") or []
    attachments = [
        Attachment(
            thumbnail=m.get("thumbnail"),
            url=m.get("url"),
            type=m.get("__typename"),
            id=str(m.get("id") or "") or None,
            ocr_text=m.get("ocrText"),
        )
        for m in media
    ]
    user = p.get("user") or {}
    # `time` is already ISO (YYYY-MM-DDTHH:mm:ss.000Z); fall back to `timestamp`.
    timestamp = p.get("time") or ""
    if not timestamp and p.get("timestamp"):
        timestamp = _iso_from_unix(int(p["timestamp"]))
    is_video = "viewsCount" in p or any(
        m.get("__typename") == "Video" for m in media
    )
    return Post(
        post_id=str(p.get("postId") or ""),
        facebook_url=p.get("url") or p.get("topLevelUrl"),
        text=text,
        author=user.get("name"),
        page_name=page_name,
        timestamp=timestamp,
        likes=int(p.get("likes") or 0),
        comments=int(p.get("comments") or 0),
        shares=int(p.get("shares") or 0),
        reactions=reactions,
        top_reactions_count=int(p.get("topReactionsCount") or 0),
        is_video=is_video,
        views=int(p.get("viewsCount") or 0),
        hashtags=_hashtags(text),
        attachments=attachments,
    )


def _call_scrapecreators(
    base_url: str, key: str, page_url: str, cursor: str | None = None
) -> dict:
    params = {"url": page_url}
    if cursor:
        params["cursor"] = cursor
    qs = urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}/v1/facebook/profile/posts?{qs}"
    data = _http_json(url, headers={"x-api-key": key})
    if not isinstance(data, dict) or not data.get("success"):
        raise RuntimeError(f"scrapecreators success=false: {str(data)[:200]}")
    return data


def _scrape_paginated(base_url: str, key: str, page_url: str, limit: int) -> list[dict]:
    """Page scrapecreators (3 posts per call) until `limit` posts or the cursor
    runs out. Fast — plain HTTP, no anti-ban delay."""
    out: list[dict] = []
    cursor: str | None = None
    while len(out) < limit:
        data = _call_scrapecreators(base_url, key, page_url, cursor)
        batch = data.get("posts") or []
        if not batch:
            break
        out.extend(batch)
        cursor = data.get("cursor")
        if not cursor:
            break
    return out[:limit]


def _call_apify(token: str, page_url: str, limit: int) -> list:
    url = (
        f"https://api.apify.com/v2/acts/{_APIFY_ACTOR}/run-sync-get-dataset-items"
        f"?token={urllib.parse.quote(token)}"
    )
    body = {"startUrls": [{"url": page_url}], "resultsLimit": limit}
    items = _http_json(url, headers={"Content-Type": "application/json"}, method="POST", body=body)
    if not isinstance(items, list):
        raise RuntimeError(f"apify unexpected response: {type(items).__name__}")
    return items


def fetch_recent(
    page_url: str,
    *,
    scrape_key: str | None = None,
    apify_token: str | None = None,
    base_url: str | None = None,
    limit: int = 3,
    max_attempts: int = 2,
) -> list[Post]:
    """Fetch up to `limit` newest posts, scrapecreators first with a retry, then
    apify as fallback. Returns normalized Posts (possibly empty)."""
    scrape_key = scrape_key or os.getenv("SCRAPE_CREATORS_API_KEY", "").strip()
    apify_token = apify_token or os.getenv("APIFY_API_TOKEN", "").strip()
    base_url = (
        base_url or os.getenv("SCRAPE_CREATORS_BASE_URL", "").strip() or _SCRAPE_BASE
    )
    page_name = page_url.rstrip("/").rsplit("/", 1)[-1] or "page"

    if scrape_key:
        for attempt in range(1, max_attempts + 1):
            try:
                posts = _scrape_paginated(base_url, scrape_key, page_url, limit)
                return [_normalize_scrapecreators(p, page_name) for p in posts]
            except Exception as exc:  # noqa: BLE001 — any failure triggers retry/fallback
                print(f"  scrapecreators attempt {attempt}/{max_attempts} failed: {exc}")

    if apify_token:
        try:
            items = _call_apify(apify_token, page_url, limit)
            return [_normalize_apify(p, page_name) for p in items[:limit]]
        except Exception as exc:  # noqa: BLE001
            print(f"  apify failed: {exc}")

    return []


def existing_post_ids(path: Path) -> set[str]:
    """Set of post_ids already written to the output file (empty if missing or
    corrupt). Used to skip the posts the crawl already captured."""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return set()
    if not isinstance(data, list):
        return set()
    return {
        p.get("post_id")
        for p in data
        if isinstance(p, dict) and p.get("post_id")
    }
