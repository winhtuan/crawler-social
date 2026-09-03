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


def _comment_media(node: dict) -> tuple[str, str]:
    """(media_type, media_url) for a comment whose content is a sticker / image
    / video instead of text. Returns ("", "") for a plain text comment.

    Facebook renders media comments with `body: null` and an `attachments`
    entry whose `style_list` plus the nested target/media __typename name the
    kind. Confirmed shape (video comment):

        attachments: [{"style_list": ["video_inline", "video", ...],
                       "style_type_renderer": {"attachment": {
                           "url": ".../videos/952536887906156/",
                           "target": {"__typename": "Video", "id": "..."},
                           "media":  {"__typename": "Video", ...}}}}]

    Sticker comments may instead carry the sticker object directly on the node.
    """
    for att in node.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        style_list = [str(s).lower() for s in (att.get("style_list") or [])]
        inner = (att.get("style_type_renderer") or {}).get("attachment") or {}
        target = inner.get("target") or {}
        media = inner.get("media") or {}
        typename = str(target.get("__typename") or media.get("__typename") or "").lower()
        url = inner.get("url") or ""
        if not url and isinstance(media, dict):
            url = media.get("playable_url") or media.get("uri") or ""
        sig = " ".join(style_list) + " " + typename
        if "sticker" in sig:
            return "sticker", url
        if "video" in sig:
            return "video", url
        if "gif" in sig or "animated" in sig:
            return "gif", url
        if "photo" in sig or "image" in sig:
            return "image", url
    sticker = node.get("sticker")
    if isinstance(sticker, dict):
        return "sticker", sticker.get("url") or sticker.get("uri") or ""
    return "", ""


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
    media_type, media_url = _comment_media(node)
    created = node.get("created_time")
    return {
        "comment_id": cid,
        "text": text,
        "media_type": media_type,
        "media_url": media_url,
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


def _reel_to_watch(url: str) -> str:
    """Rewrite a /reel/<id>/ permalink to /watch/?v=<id>.

    Facebook serves the /reel/<id>/ URL as a fullscreen player with NO
    server-rendered comments and no comment GraphQL responses, so the comment
    pass on a reel permalink finds nothing. The watch URL (which redirects to the
    page's /videos/<id>/) serves comments in SSR HTML and paginates on scroll —
    the same path photo-post permalinks take. Non-reel URLs pass through."""
    m = re.search(r"/reel/(\d+)", url)
    if m:
        return f"https://www.facebook.com/watch/?v={m.group(1)}"
    return url


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
        # Owning post_id -> {comment_id: flattened comment}. Bucketing happens in
        # add_nodes so comments_for_post is an O(1) lookup, not an O(n) scan.
        self.by_post: dict[str, dict[str, dict]] = {}

    def attach(self) -> None:
        self._page.on("response", self._on_response)

    def detach(self) -> None:
        try:
            self._page.remove_listener("response", self._on_response)
        except Exception:
            pass

    def add_nodes(self, nodes: list[dict]) -> None:
        """Merge raw Comment nodes into by_id (deduped, first wins), bucketing
        each comment under its owning post id (decoded from its Relay id)."""
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
                self.by_post.setdefault(pid, {})[cid] = c

    def comments_for_post(self, post_id: str) -> dict[str, dict]:
        """Comments whose decoded owning post id matches post_id (numeric)."""
        return self.by_post.get(post_id, {}) if post_id else {}

    async def _on_response(self, resp) -> None:
        if "/api/graphql/" not in resp.url or resp.status != 200:
            return
        try:
            text = await resp.text()
        except Exception:
            return
        self.add_nodes(extract_comments(split_json_values(text)))


# Label-classifier regexes for 'view more comments/replies' buttons (vi/en).
# Single source of truth: `_is_view_more_label` tests these in Python, and the
# JS below embeds the exact same patterns, so the in-page behaviour is locked.
_VIEW_MORE_START = r"^(xem|view|hiển thị)"
_VIEW_MORE_KIND = r"(bình luận|nhận xét|câu trả lời|phản hồi|replies|reply|comment)"
_COMPOSER_HINT = r"viết bình luận|write a comment|viết nhận xét"
_VIEW_MORE_MAX_LEN = 90


def _is_view_more_label(text: str) -> bool:
    """True for a tight 'view more comments/replies' button label (vi/en): short
    normalized text starting with xem/view/hiển thị, containing a comment/reply
    word, and NOT the full-width comment composer placeholder."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    return (
        re.search(_VIEW_MORE_START, t, re.I) is not None
        and re.search(_VIEW_MORE_KIND, t, re.I) is not None
        and len(t) < _VIEW_MORE_MAX_LEN
        and re.search(_COMPOSER_HINT, t, re.I) is None
    )


_VIEW_MORE_JS = f"""() => {{
    const norm = (t) => (t || '').replace(/\\s+/g, ' ').trim();
    const isLabel = (t) =>
        /{_VIEW_MORE_START}/i.test(t) &&
        /{_VIEW_MORE_KIND}/i.test(t) &&
        t.length < {_VIEW_MORE_MAX_LEN};
    const els = [...document.querySelectorAll('span[dir="auto"], div[role="button"], a, [role="button"]')];
    const clicked = new Set();
    let n = 0;
    for (const e of els) {{
        const t = norm(e.textContent);
        if (!isLabel(t)) continue;
        // skip the full-width comment composer ("Viết bình luận...")
        if (/{_COMPOSER_HINT}/i.test(t)) continue;
        let c = e;
        while (c && c.tagName !== 'BODY') {{
            if (c.getAttribute('role') === 'button' || c.tagName === 'A') break;
            c = c.parentElement;
        }}
        if (!c || c.tagName === 'BODY') c = e;
        if (clicked.has(c)) continue;
        clicked.add(c);
        c.click(); n++;
    }}
    return n;
}}"""


async def _click_view_more(page) -> int:
    """Click every 'View more comments' AND 'View more replies' button currently
    in the DOM (vi/en). Returns how many were clicked. Matches only tight button
    labels (short trimmed text starting with xem/view/hiển thị), so a big
    container whose textContent merely mentions 'comment' won't match. Dedupes by
    the resolved clickable element (not by label text), so every post's button is
    clicked — the feed shows one 'Xem thêm bình luận' per post, and deduping by
    text would click only the first."""
    return int(await page.evaluate(_VIEW_MORE_JS))


async def scroll_comment_list(page) -> bool:
    """Scroll every scrollable div to its bottom to trigger Facebook's
    infinite-scroll comment pagination.

    The logged-in permalink loads older comments by scrolling the comment-list
    container — there is no 'view more comments' button in the current UI, and
    scrolling the window does nothing (the comment list is its own scroll div).
    Each scroll fires a GraphQL request the CommentInterceptor captures. Returns
    True when at least one container actually moved.
    """
    return bool(await page.evaluate(
        """() => {
            let any = false;
            document.querySelectorAll('div').forEach(d => {
                if (d.scrollHeight > d.clientHeight + 100 && d.clientHeight > 100) {
                    if (d.scrollTop < d.scrollHeight - d.clientHeight - 1) {
                        d.scrollTop = d.scrollHeight;
                        any = true;
                    }
                }
            });
            return any;
        }"""
    ))


async def expand_comments(page, cfg, rounds: int = 4) -> int:
    """Expand the inline comment sections by scrolling the comment-list
    container (older comments) and clicking every 'view replies' button (nested
    replies) for a few rounds. Each action fires a GraphQL request the
    CommentInterceptor captures (and buckets by post). Returns the total number
    of buttons clicked.

    Uses a short per-click delay (independent of the scroll-level anti-bot
    delay) so many rounds can run in a bounded time — a 200-comment post needs
    ~15 scrolls, which must not each cost cfg.delay_base seconds."""
    human = Humanizer(base=min(cfg.delay_base, 0.8), jitter=0.35)
    total = 0
    # Let the comment section hydrate before the first pass — the reply buttons
    # render asynchronously after the post card, and scrolling too early finds
    # nothing.
    await asyncio.sleep(0.6)
    zero_streak = 0
    for _ in range(rounds):
        await scroll_comment_list(page)
        await asyncio.sleep(0.5)
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


async def _click_exact_text(page, text: str) -> bool:
    """Click the first clickable element whose normalized text equals `text`
    exactly. Exact match avoids grabbing a container whose textContent merely
    contains the label alongside a description."""
    return bool(await page.evaluate(
        """(t) => {
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const sel = [...document.querySelectorAll(
                '[role="button"], a, [role="menuitem"], [role="option"], [role="radio"], span[dir="auto"]')];
            for (const e of sel) {
                if (norm(e.textContent) === t) { e.click(); return true; }
            }
            return false;
        }""",
        text,
    ))


async def switch_to_all_comments(page) -> bool:
    """Switch the permalink's comment sort to 'All comments' so spam-filtered
    comments load too. The permalink defaults to 'Most relevant', which hides
    low-relevance comments. No-op (False) when the sort control is absent or
    already set."""
    opened = False
    for trigger in ("Phù hợp nhất", "Mới nhất", "Most relevant", "Newest"):
        if await _click_exact_text(page, trigger):
            opened = True
            await asyncio.sleep(0.8)
            break
    if not opened:
        return False
    return (await _click_exact_text(page, "Tất cả bình luận")
            or await _click_exact_text(page, "All comments"))


def _sort_and_cap(records: list[dict], max_comments: int) -> list[dict]:
    """Sort flat comment records by (likes, date) descending and cap at
    max_comments (<=0 means no cap). Shared by collect_comments and the graphql
    fetch path so both produce the same output shape."""
    records.sort(key=lambda c: (c.get("likes") or 0, c.get("date") or ""), reverse=True)
    limit = max_comments if max_comments > 0 else 10**9
    return records[:limit]


def collect_comments(interceptor: CommentInterceptor, post_url: str,
                     post_id: str, max_comments: int) -> list[dict]:
    """Return the comments bucketed to post_id by a populated CommentInterceptor
    (fed by expand_comments during feed collection). Sorted by likes descending
    (most-liked first; ties by date descending), capped at max_comments (<=0
    means no cap) — so a >max_comments post keeps its top comments. Each
    comment_url is rewritten to point at this post's permalink."""
    out: list[dict] = []
    for c in interceptor.comments_for_post(post_id).values():
        c = dict(c)
        if post_url:
            c["comment_url"] = f"{post_url}?comment_id={c['comment_id']}"
        out.append(c)
    return _sort_and_cap(out, max_comments)
