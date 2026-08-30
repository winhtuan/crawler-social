from __future__ import annotations
import base64
from crawlfb.models import Post, User, Media, PhotoImage, MediaFeedback


def feedback_id(post_id: str) -> str:
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def top_level_url(page_id: str, post_id: str) -> str:
    return f"https://www.facebook.com/{page_id}/posts/{post_id}"


def _normalize_media(m: dict) -> Media:
    img = m.get("photo_image") or {}
    fb = m.get("feedback") or {}
    return Media(
        thumbnail=m.get("thumbnail"),
        __typename=m.get("__typename"),
        __isMedia=m.get("__isMedia"),
        accent_color=m.get("accent_color"),
        photo_product_tags=m.get("photo_product_tags") or [],
        photo_image=PhotoImage(uri=img["uri"], height=img.get("height"), width=img.get("width"))
        if img.get("uri") else None,
        url=m.get("url"),
        id=str(m["id"]) if m.get("id") else None,
        feedback=MediaFeedback(
            can_viewer_comment=bool(fb.get("can_viewer_comment", False)),
            id=fb.get("id"),
        ),
        ocrText=m.get("ocr_text"),
    )


def normalize_post(raw: dict, input_url: str, page_name: str) -> Post:
    page_id = str(raw.get("page_id", ""))
    post_id = str(raw.get("post_id", ""))
    reactions = raw.get("reaction_counts") or {}
    post = Post(
        facebookUrl=input_url,
        postId=post_id,
        pageName=page_name,
        url=raw.get("permalink_url") or top_level_url(page_id, post_id),
        time=raw.get("created_time_iso"),
        timestamp=raw.get("created_unix"),
        user=User(
            id=str(raw.get("author_id", "")),
            name=raw.get("author_name", "") or page_name,
            profileUrl=raw.get("author_profile_url", ""),
            profilePic=raw.get("author_profile_pic", ""),
        ),
        text=raw.get("text"),
        comments=int(raw.get("comment_count") or 0),
        shares=int(raw.get("share_count") or 0),
        media=[_normalize_media(m) for m in raw.get("media") or []],
        feedbackId=feedback_id(post_id),
        reactionHahaCount=int(reactions.get("HAHA") or 0),
        reactionLikeCount=int(reactions.get("LIKE") or 0),
        reactionSadCount=int(reactions.get("SAD") or 0),
        reactionLoveCount=int(reactions.get("LOVE") or 0),
        paidPartnership=bool(raw.get("paid_partnership", False)),
        topLevelUrl=top_level_url(page_id, post_id),
        facebookId=page_id,
        inputUrl=input_url,
    )
    post.likes = sum(post.model_dump().get(k, 0) for k in (
        "reactionHahaCount", "reactionLikeCount", "reactionSadCount", "reactionLoveCount",
    ))
    post.topReactionsCount = sum(
        1 for v in (post.reactionHahaCount, post.reactionLikeCount,
                    post.reactionSadCount, post.reactionLoveCount) if v > 0
    )
    return post
