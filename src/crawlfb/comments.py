from __future__ import annotations
import asyncio
import base64
import json
import re
from datetime import datetime, timezone
from crawlfb.humanizer import Humanizer
from crawlfb.intercept import split_json_values, _deep_get, _to_int


def _iso(unix) -> str:
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return ""


def _comment_id(node: dict) -> str:
    """Numeric comment id. Prefers legacy_fbid (the clean numeric id FB exposes
    on Comment nodes), then legacy_comment_id / comment_id, then id. When only
    the base64 Relay id ("comment:<post>_<id>") is present, decode it back to the
    numeric id so it dedupes against the full node."""
    for key in ("legacy_fbid", "legacy_comment_id", "comment_id"):
        v = node.get(key)
        if v:
            s = str(v)
            if "_" in s:
                s = s.rsplit("_", 1)[-1]
            return s
    v = node.get("id")
    if v:
        s = str(v)
        if "_" in s:
            return s.rsplit("_", 1)[-1]
        try:
            dec = base64.b64decode(s).decode("utf-8")
            if ":" in dec:
                dec = dec.rsplit(":", 1)[-1]
            if "_" in dec:
                dec = dec.rsplit("_", 1)[-1]
            return dec
        except Exception:
            return s
    return ""


def _is_real_comment(v: dict) -> bool:
    """True for a populated Comment node. Facebook embeds these two ways:

      1. SSR / older graphql: {__typename: "Comment", legacy_fbid, body, ...}
      2. Feed & "view more" graphql: each comment is wrapped as {"comment": {...}}
         with NO __typename, but still carries legacy_fbid + body + author.

    So key on the fields, not __typename. Bare Relay references ({id: base64}
    only, no legacy_fbid/body/author) are skipped."""
    has_id = bool(
        v.get("legacy_fbid") or v.get("legacy_comment_id") or v.get("comment_id")
    )
    has_content = v.get("body") is not None or v.get("author") is not None
    return has_id and has_content


def _comment_post_id(node: dict) -> str:
    """The numeric id of the post a comment belongs to, decoded from the
    comment's Relay id ("comment:<post_id>_<comment_id>"). Empty when the id is
    absent or can't be decoded."""
    cid = node.get("id")
    if not cid:
        return ""
    s = str(cid)
    if "_" in s:
        # "comment:1122_1781" -> "1122"; plain "1122_1781" -> "1122"
        head = s.rsplit("_", 1)[0]
        return head.rsplit(":", 1)[-1]
    try:
        dec = base64.b64decode(s).decode("utf-8")
    except Exception:
        return ""
    if ":" in dec:
        dec = dec.rsplit(":", 1)[-1]
    if "_" in dec:
        return dec.rsplit("_", 1)[0]
    return ""


def _comment_likes(node: dict) -> int:
    """Reaction count on a comment. Lives at
    comment_action_links[*].comment.feedback.reactors.count (int). Falls back to
    the display string feedback.reactors.count_reduced (may be "1.2K")."""
    for cal in node.get("comment_action_links") or []:
        if not isinstance(cal, dict):
            continue
        fb = _deep_get(cal, "comment", "feedback") or {}
        v = _deep_get(fb, "reactors", "count")
        if v is None:
            v = _deep_get(fb, "unified_reactors", "count")
        if v is not None:
            return _to_int(v)
    return _to_int(_deep_get(node, "feedback", "reactors", "count_reduced"))


def flatten_comment(node: dict, post_url: str) -> dict:
    """Map one raw Comment node to the flat comment record."""
    cid = _comment_id(node)
    body = node.get("body")
    if isinstance(body, dict):
        text = body.get("text") or ""
    elif isinstance(body, str):
        text = body
    else:
        text = ""
    created = node.get("created_time")
    return {
        "comment_id": cid,
        "text": text,
        "author": _deep_get(node, "author", "name") or "",
        "likes": _comment_likes(node),
        "date": _iso(created) if created is not None else "",
        "threading_depth": _to_int(node.get("depth")),
        "comment_url": f"{post_url}?comment_id={cid}" if cid else post_url,
    }


def _walk(value, out: list[dict], seen: set[str], pred) -> None:
    if isinstance(value, dict):
        if pred(value):
            cid = _comment_id(value)
            if cid and cid not in seen:
                seen.add(cid)
                out.append(value)
        for sub in value.values():
            _walk(sub, out, seen, pred)
    elif isinstance(value, list):
        for sub in value:
            _walk(sub, out, seen, pred)


def extract_comments(batch: list) -> list[dict]:
    """Return raw Comment nodes from a list of decoded JSON values, deduped by
    comment id. Skips bare Relay reference nodes (no body/legacy_fbid)."""
    out: list[dict] = []
    seen: set[str] = set()
    for value in batch:
        _walk(value, out, seen, _is_real_comment)
    return out


_SCRIPT_RE = re.compile(
    r'<script type="application/json"[^>]*>(.*?)</script>', re.S
)


def extract_comments_from_html(html: str) -> list[dict]:
    """Extract Comment nodes from the page's server-side-rendered JSON. Facebook
    embeds the initial comments in <script type="application/json" data-sjs>
    blocks, not in the /api/graphql/ responses (those only carry
    comment_rendering_instance.total_count)."""
    out: list[dict] = []
    seen: set[str] = set()
    for m in _SCRIPT_RE.finditer(html):
        try:
            obj = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        for node in extract_comments([obj]):
            cid = _comment_id(node)
            if cid and cid not in seen:
                seen.add(cid)
                out.append(node)
    return out


def _permalink_key(url: str) -> str:
    """Canonical key for a post/reel permalink: "posts/<pfbid>" or
    "reel/<id>". Used to match a comment back to the post it belongs to."""
    m = re.search(r"/(posts|reel|videos|watch)/([^/?#]+)", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return url.rstrip("/").rsplit("/", 1)[-1]


def _comment_permalink(node: dict) -> str:
    """The post permalink a comment belongs to, from its feedback.url (with the
    ?comment_id= suffix stripped). Empty when absent."""
    url = _deep_get(node, "feedback", "url") or ""
    return url.split("?")[0]


class CommentInterceptor:
    """Collects every Comment node from Facebook's in-browser GraphQL responses,
    flattened and keyed by numeric comment_id. The feed and 'view more' graphql
    responses carry comments for MANY posts (not just the one being expanded),
    and the permalink on each comment is unreliable, so no post filter is applied
    here. Callers bucket a post's comments via :meth:`comments_for_post`, which
    keys on the numeric post id decoded from each comment's Relay id."""

    def __init__(self, page):
        self._page = page
        self.by_id: dict[str, dict] = {}
        self.post_of: dict[str, str] = {}  # comment_id -> numeric post_id

    def attach(self) -> None:
        self._page.on("response", self._on_response)

    def detach(self) -> None:
        try:
            self._page.remove_listener("response", self._on_response)
        except Exception:
            pass

    def add_nodes(self, nodes: list[dict]) -> None:
        """Merge raw Comment nodes into by_id (deduped, first wins), recording
        each comment's owning post id (decoded from its Relay id)."""
        for node in nodes:
            try:
                c = flatten_comment(node, "")
            except Exception:
                continue
            cid = c.get("comment_id")
            if not cid or cid in self.by_id:
                continue
            self.by_id[cid] = c
            pid = _comment_post_id(node)
            if pid:
                self.post_of[cid] = pid

    def comments_for_post(self, post_id: str) -> dict[str, dict]:
        """Comments whose decoded owning post id matches post_id (numeric)."""
        return {
            cid: self.by_id[cid]
            for cid, pid in self.post_of.items()
            if post_id and pid == post_id
        }

    async def _on_response(self, resp) -> None:
        if "/api/graphql/" not in resp.url or resp.status != 200:
            return
        try:
            text = await resp.text()
        except Exception:
            return
        self.add_nodes(extract_comments(split_json_values(text)))


async def _click_view_more(page) -> int:
    """Click every 'View more comments' AND 'View more replies' button currently
    in the DOM (vi/en). Returns how many were clicked. Matches only tight button
    labels (short trimmed text starting with xem/view/hiển thị), so a big
    container whose textContent merely mentions 'comment' won't match. Dedupes by
    the resolved clickable element (not by label text), so every post's button is
    clicked — the feed shows one 'Xem thêm bình luận' per post, and deduping by
    text would click only the first."""
    return int(await page.evaluate(
        """() => {
            const norm = (t) => (t || '').replace(/\\s+/g, ' ').trim();
            const isLabel = (t) =>
                /^(xem|view|hiển thị)/i.test(t) &&
                /(bình luận|nhận xét|câu trả lời|phản hồi|reply|comment)/i.test(t) &&
                t.length < 90;
            const els = [...document.querySelectorAll('span[dir="auto"], div[role="button"], a, [role="button"]')];
            const clicked = new Set();
            let n = 0;
            for (const e of els) {
                const t = norm(e.textContent);
                if (!isLabel(t)) continue;
                // skip the full-width comment composer ("Viết bình luận...")
                if (/viết bình luận|write a comment|viết nhận xét/i.test(t)) continue;
                let c = e;
                while (c && c.tagName !== 'BODY') {
                    if (c.getAttribute('role') === 'button' || c.tagName === 'A') break;
                    c = c.parentElement;
                }
                if (!c || c.tagName === 'BODY') c = e;
                if (clicked.has(c)) continue;
                clicked.add(c);
                c.click(); n++;
            }
            return n;
        }"""
    ))


async def expand_comments(page, cfg, rounds: int = 4) -> int:
    """Expand the inline comment sections of the visible feed posts by clicking
    every 'view more comments' / 'view replies' button for a few rounds. Each
    click fires a GraphQL request the CommentInterceptor captures (and buckets
    by post). Returns the total number of buttons clicked.

    Uses a short per-click delay (independent of the scroll-level anti-bot
    delay) so many 'view more' clicks can run in a bounded time — a 321-comment
    post needs ~15 clicks, which must not each cost cfg.delay_base seconds."""
    human = Humanizer(base=min(cfg.delay_base, 0.8), jitter=0.35)
    total = 0
    # Let the comment section hydrate before the first pass — the 'view more'
    # button renders asynchronously after the post card, and clicking too early
    # finds nothing.
    await asyncio.sleep(0.6)
    zero_streak = 0
    for _ in range(rounds):
        clicked = await _click_view_more(page)
        total += clicked
        if clicked == 0:
            zero_streak += 1
            if zero_streak >= 2:
                break
            # Buttons may still be hydrating; wait and retry before giving up.
            await asyncio.sleep(0.8)
            continue
        zero_streak = 0
        await human.pause()
        await asyncio.sleep(0.5)
    return total


async def expand_feed_topdown(page, cfg, steps: int = 16, rounds: int = 8) -> int:
    """Expand comment sections top-to-bottom over the already-collected feed.
    Feed virtualization drops a post's inline 'view more' button once it scrolls
    out of view, so the collection pass only fully expands the posts near the
    bottom. This re-walks the feed from the top, expanding each post's comments
    while it is on screen, then scrolling down a step. Comments are bucketed by
    post id, so the order does not matter."""
    human = Humanizer(base=min(cfg.delay_base, 0.9), jitter=0.4)
    total = 0
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(1.5)
    for _ in range(steps):
        total += await expand_comments(page, cfg, rounds=rounds)
        await page.evaluate("window.scrollBy(0, 700)")
        await human.pause()
    return total


def collect_comments(interceptor: CommentInterceptor, post_url: str,
                     post_id: str, max_comments: int) -> list[dict]:
    """Return the comments bucketed to post_id by a populated CommentInterceptor
    (fed by expand_comments during feed collection). Sorted by date ascending,
    capped at max_comments (<=0 means no cap). Each comment_url is rewritten to
    point at this post's permalink."""
    out: list[dict] = []
    for c in interceptor.comments_for_post(post_id).values():
        c = dict(c)
        if post_url:
            c["comment_url"] = f"{post_url}?comment_id={c['comment_id']}"
        out.append(c)
    out.sort(key=lambda c: c.get("date") or "")
    limit = max_comments if max_comments > 0 else 10**9
    return out[:limit]
