from __future__ import annotations
import re
from crawlfb.models import Post, Attachment, TopComment, Comment

# Uppercase reaction keys from the feed -> lowercase keys in the output.
_REACTION_KEY_MAP = {
    "LIKE": "like",
    "LOVE": "love",
    "CARE": "care",
    "HAHA": "haha",
    "WOW": "wow",
    "SAD": "sad",
    "ANGRY": "angry",
}


def _hashtags(text: str | None) -> list[str]:
    """Extract #hashtags from post text, preserving case and order."""
    return re.findall(r"#[\w]+", text or "")


def _reactions(raw: dict) -> dict[str, int]:
    counts = raw.get("reaction_counts") or {}
    out: dict[str, int] = {}
    for upper, lower in _REACTION_KEY_MAP.items():
        try:
            n = int(counts.get(upper) or 0)
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            out[lower] = n
    return out


def normalize_post(raw: dict, page_name: str, comments: list[dict] | None = None) -> Post:
    """Map a flattened raw Story (plus its scraped comments) to the
    facebook-comments-scraper output record."""
    comments = comments or []
    reactions = _reactions(raw)
    attachments = [Attachment(**a) for a in raw.get("attachments") or []]
    comments_list = [Comment(**c) for c in comments]
    top_comments = [
        TopComment(
            text=c.get("text") or "",
            author=c.get("author") or "",
            likes=int(c.get("likes") or 0),
        )
        for c in comments[:1]
    ]
    return Post(
        facebook_url=raw.get("permalink_url"),
        text=raw.get("text"),
        author=raw.get("author_name") or page_name,
        page_name=page_name,
        timestamp=raw.get("created_time_iso"),
        likes=sum(reactions.values()),
        comments=int(raw.get("comment_count") or 0),
        shares=int(raw.get("share_count") or 0),
        reactions=reactions,
        top_reactions_count=len(reactions),
        top_comments=top_comments,
        comments_list=comments_list,
        is_video=bool(raw.get("is_video")),
        views=int(raw.get("views") or 0),
        hashtags=_hashtags(raw.get("text")),
        attachments=attachments,
        post_id=str(raw.get("post_id") or ""),
    )
