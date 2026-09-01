from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional

# Stable Facebook reaction IDs (empirical from the captured feed fixture).
_REACTION_ID_MAP = {
    "1635855486666999": "LIKE",
    "1678524932434102": "LOVE",
    "613557422527005": "CARE",
    "613557422527858": "CARE",
    "115940658764963": "HAHA",
    "478547315650144": "WOW",
    "908563459236466": "SAD",
    "444813342392137": "ANGRY",
}
# Fallback by localized_name (Vietnamese locale).
_REACTION_NAME_MAP = {
    "Thích": "LIKE",
    "Yêu thích": "LOVE",
    "Thương thương": "CARE",
    "Haha": "HAHA",
    "Wow": "WOW",
    "Buồn": "SAD",
    "Phẫn nộ": "ANGRY",
}


def split_json_values(text: str) -> list:
    """Facebook graphql batch responses concatenate several JSON values with no
    wrapping array, so resp.json() fails on them ("Extra data"). Split manually."""
    dec = json.JSONDecoder()
    out = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(text, i)
            out.append(obj)
        except json.JSONDecodeError:
            i += 1
    return out


def _walk_stories(value, out: list[dict], seen: set[str]) -> None:
    if isinstance(value, dict):
        if value.get("__typename") == "Story" and value.get("post_id"):
            pid = str(value["post_id"])
            if pid not in seen:
                seen.add(pid)
                out.append(value)
        for sub in value.values():
            _walk_stories(sub, out, seen)
    elif isinstance(value, list):
        for sub in value:
            _walk_stories(sub, out, seen)


def extract_stories(batch: list) -> list[dict]:
    """Return raw Story nodes from a GraphQL feed batch (a list of decoded JSON
    values). Walks every dict/list inside each value; collects every dict with
    __typename == "Story" and a post_id, in encounter order, deduped by post_id
    (first wins)."""
    out: list[dict] = []
    seen: set[str] = set()
    for value in batch:
        _walk_stories(value, out, seen)
    return out


def _deep_get(node, *path):
    cur = node
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _feedback(node: dict):
    """The feedback object of a Story node (R4-E). Every level may be missing."""
    return _deep_get(
        node,
        "comet_sections", "feedback", "story", "story_ufi_container", "story",
        "feedback_context", "feedback_target_with_context",
        "comet_ufi_summary_and_actions_renderer", "feedback",
    )


def _reaction_counts(fb) -> dict:
    """Map top_reactions edges to type names found (up to all 7)."""
    counts: dict[str, int] = {}
    for edge in _deep_get(fb, "top_reactions", "edges") or []:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node") or {}
        rid = str(node.get("id") or "")
        name = (node.get("localized_name") or "").strip()
        type_name = _REACTION_ID_MAP.get(rid) or _REACTION_NAME_MAP.get(name)
        if not type_name:
            continue
        try:
            count = int(edge.get("reaction_count") or 0)
        except (TypeError, ValueError):
            count = 0
        counts[type_name] = count
    return counts


def _to_int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _comment_count(fb) -> int:
    # Logged-in feed: adaptive_ufi_action_renderers[i].feedback.
    #                   comment_rendering_instance.comments.total_count
    for renderer in _deep_get(fb, "adaptive_ufi_action_renderers") or []:
        total = _deep_get(
            renderer, "feedback", "comment_rendering_instance", "comments", "total_count"
        )
        if total is not None:
            return _to_int(total)
    # Logged-out fixture: comments_count_summary_renderer.feedback.
    #                      comment_rendering_instance.comments.total_count
    return _to_int(_deep_get(
        fb, "comments_count_summary_renderer", "feedback",
        "comment_rendering_instance", "comments", "total_count",
    ))


def _share_count(fb) -> int:
    # Logged-in feed: adaptive_ufi_action_renderers[i].feedback.share_count.count
    for renderer in _deep_get(fb, "adaptive_ufi_action_renderers") or []:
        cnt = _deep_get(renderer, "feedback", "share_count", "count")
        if cnt is not None:
            return _to_int(cnt)
    # Logged-out fixture: share_count.count
    return _to_int(_deep_get(fb, "share_count", "count"))


def _views(fb) -> int:
    """Video view count. Prefer the top-level video_view_count, then the
    renderer's, then play_count as a last resort."""
    v = _deep_get(fb, "video_view_count")
    if v is not None:
        return _to_int(v)
    renderer = _deep_get(fb, "video_view_count_renderer", "feedback") or {}
    v = _deep_get(renderer, "video_view_count")
    if v is not None:
        return _to_int(v)
    v = _deep_get(renderer, "play_count")
    if v is not None:
        return _to_int(v)
    return 0


def _is_video(node: dict, fb) -> bool:
    if _deep_get(fb, "associated_video", "id"):
        return True
    if _deep_get(fb, "video_view_count") is not None:
        return True
    for att in node.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        m = _deep_get(att, "styles", "attachment", "media") or att.get("media") or {}
        if (m.get("__typename") or "") == "Video":
            return True
    return False


def _attachments(node: dict) -> list:
    """Map Story attachments to the flat {thumbnail,url,type,id,ocr_text}
    shape. The full media node lives at styles.attachment.media (the shallow
    attachments[*].media carries only __typename/id)."""
    out = []
    for att in node.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        styles = att.get("styles") or {}
        m = _deep_get(styles, "attachment", "media")
        if not isinstance(m, dict):
            m = att.get("media")
        if not isinstance(m, dict):
            continue
        typename = m.get("__typename") or ""
        mid = str(m["id"]) if m.get("id") else None
        if typename == "Photo":
            img = m.get("photo_image") or {}
            if not img.get("uri"):
                continue
            out.append({
                "thumbnail": img.get("uri"),
                "url": m.get("url"),
                "type": "Photo",
                "id": mid,
                "ocr_text": m.get("ocr_text"),
            })
        elif typename == "Video":
            thumb = m.get("thumbnailImage") or {}
            out.append({
                "thumbnail": thumb.get("uri"),
                "url": m.get("url") or _deep_get(styles, "attachment", "url"),
                "type": "Video",
                "id": mid,
                "ocr_text": None,
            })
    return out


def is_reel(raw: dict) -> bool:
    """True when a flattened Story is a reel (its permalink points at /reel/).
    Reels are dropped from output — their comments live in a drawer, not inline
    like a regular post (see docs/adr/0002-exclude-reels.md)."""
    return "/reel/" in (raw.get("permalink_url") or "")


def flatten(node: dict, page_id: str, page_name: str) -> dict:
    """Map one raw Story node to the flat RawStory contract."""
    post_id = str(node.get("post_id") or "")
    actors = node.get("actors") or []
    author = actors[0] if actors else {}
    author_id = str(author.get("id") or "")
    resolved_page_id = str(page_id or "") or author_id
    author_profile_url = f"https://www.facebook.com/{author_id}" if author_id else ""

    creation_time = node.get("creation_time")
    created_unix = 0
    created_time_iso = ""
    if creation_time is not None:
        try:
            created_unix = int(creation_time)
            created_time_iso = datetime.fromtimestamp(
                created_unix, tz=timezone.utc
            ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (TypeError, ValueError, OSError):
            created_unix = 0

    text = _deep_get(node, "comet_sections", "content", "story", "message", "text") or ""
    fb = _feedback(node)
    return {
        "post_id": post_id,
        "page_id": resolved_page_id,
        "author_id": author_id,
        "author_name": author.get("name") or "",
        "author_profile_url": author_profile_url,
        "author_profile_pic": "",
        "text": text,
        "created_time_iso": created_time_iso,
        "created_unix": created_unix,
        "reaction_counts": _reaction_counts(fb),
        "comment_count": _comment_count(fb),
        "share_count": _share_count(fb),
        "permalink_url": node.get("permalink_url") or "",
        "attachments": _attachments(node),
        "is_video": _is_video(node, fb),
        "views": _views(fb),
    }


class FeedInterceptor:
    """Collects posts by watching Facebook's in-browser GraphQL feed responses."""

    def __init__(self, page, page_id: Optional[str] = None, page_name: str = ""):
        self._page = page
        self._page_id = page_id
        self._page_name = page_name
        self._seen: set[str] = set()
        self.posts: list[dict] = []  # flattened RawStory dicts, ordered, deduped

    def attach(self) -> None:
        self._page.on("response", self._on_response)

    def detach(self) -> None:
        try:
            self._page.remove_listener("response", self._on_response)
        except Exception:
            pass

    async def _on_response(self, resp) -> None:
        if "/api/graphql/" not in resp.url or resp.status != 200:
            return
        try:
            text = await resp.text()
        except Exception:
            return
        for node in extract_stories(split_json_values(text)):
            try:
                raw = flatten(node, self._page_id or "", self._page_name)
            except Exception:
                continue
            pid = raw.get("post_id")
            if pid and pid not in self._seen:
                self._seen.add(pid)
                self.posts.append(raw)
