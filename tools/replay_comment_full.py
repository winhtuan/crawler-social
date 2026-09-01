"""One-off: fetch ALL comments for a post by replaying the comment GraphQL
queries (root + pagination) directly — no permalink navigation, no scroll.

Run:  python tools/replay_comment_full.py <bootstrap_permalink> <target_post_id> [out.json]

Loads <bootstrap_permalink> only to capture the session-tied form fields
(fb_dtsg, lsd, __dyn, ...). Then fetches every page of comments for
<target_post_id> (a different post) via in-page fetch. Prints the total unique
comment count, proving the crawl can drop per-post page.goto().
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

from crawlfb.comments import _comment_id, split_json_values, switch_to_all_comments
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context

ROOT_DOC = "27046361795040764"
ROOT_NAME = "CommentListComponentsRootQuery"
PAGE_DOC = "27973447728944010"
PAGE_NAME = "CommentsListComponentsPaginationQuery"

_RELAY = {
    "__relay_internal__pv__CometUFICommentAutoTranslationTyperelayprovider": "AUTO_TRANSLATE",
    "__relay_internal__pv__CometUFICommentAvatarStickerAnimatedImagerelayprovider": False,
    "__relay_internal__pv__CometUFICommentActionLinksRewriteEnabledrelayprovider": True,
    "__relay_internal__pv__IsWorkUserrelayprovider": False,
}

_FETCH_JS = """async (body) => {
    const r = await fetch('/api/graphql/', {
        method: 'POST',
        headers: {'content-type': 'application/x-www-form-urlencoded'},
        body: body,
        credentials: 'include',
    });
    return await r.text();
}"""


def _fid(post_id: str) -> str:
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def _root_vars(post_id: str) -> dict:
    return {
        "commentsIntentToken": "RANKED_UNFILTERED_CHRONOLOGICAL_REPLIES_INTENT_V1",
        "feedLocation": "POST_PERMALINK_DIALOG",
        "feedbackSource": 2,
        "focusCommentID": None,
        "scale": 1,
        "useDefaultActor": False,
        "id": _fid(post_id),
        **_RELAY,
    }


def _page_vars(post_id: str, cursor: str) -> dict:
    return {
        "commentsAfterCount": -1,
        "commentsAfterCursor": cursor,
        "commentsBeforeCount": None,
        "commentsBeforeCursor": None,
        "commentsIntentToken": "RANKED_UNFILTERED_CHRONOLOGICAL_REPLIES_INTENT_V1",
        "feedLocation": "POST_PERMALINK_DIALOG",
        "focusCommentID": None,
        "scale": 1,
        "targetDialect": None,
        "useDefaultActor": False,
        "id": _fid(post_id),
        **_RELAY,
    }


def _deep(node, *path):
    cur = node
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _comments_block(values: list) -> dict | None:
    """The {edges, page_info} block for the requested post's comments."""
    for v in values:
        block = _deep(v, "data", "node", "comment_rendering_instance_for_feed_location", "comments")
        if isinstance(block, dict) and "edges" in block:
            return block
    return None


async def _post(page, form: dict, doc: str, name: str, variables: dict) -> list:
    body = urllib.parse.urlencode({**form, "doc_id": doc,
                                   "fb_api_req_friendly_name": name,
                                   "variables": json.dumps(variables)})
    raw = await page.evaluate(_FETCH_JS, body)
    return split_json_values(raw)


async def main(bootstrap: str, target_id: str, out: str) -> None:
    load_dotenv()
    cfg = Config(
        page_url=bootstrap,
        output="x.json",
        max_posts=1,
        headless=True,
        proxy=Proxy.from_url(os.getenv("HTTP_PROXY")),
        storage_state=os.getenv("FB_STORAGE_STATE", ".storage_state.json"),
    )
    form: dict | None = None

    async with launch_context(cfg) as (_ctx, page):
        async def on_request(req) -> None:
            nonlocal form
            if form is not None:
                return
            if "/api/graphql/" in req.url and req.method == "POST":
                try:
                    b = req.post_data
                except Exception:
                    return
                if ROOT_DOC in b:
                    form = dict(urllib.parse.parse_qsl(b))

        page.on("request", on_request)
        await page.goto(bootstrap, wait_until="domcontentloaded", timeout=60000)
        await switch_to_all_comments(page)
        for _ in range(20):
            if form is not None:
                break
            await asyncio.sleep(0.5)
        if form is None:
            print("FAIL: no root query captured")
            return

        # Page 1 (root) then paginate until has_next_page is false.
        comments: dict[str, dict] = {}
        values = await _post(page, form, ROOT_DOC, ROOT_NAME, _root_vars(target_id))
        block = _comments_block(values)
        pages = 1
        while block is not None:
            for e in block.get("edges") or []:
                node = e.get("node") if isinstance(e, dict) else None
                if not node:
                    continue
                cid = _comment_id(node)
                if cid and cid not in comments:
                    comments[cid] = node
            info = block.get("page_info") or {}
            if not info.get("has_next_page"):
                break
            cursor = info.get("end_cursor")
            if not cursor:
                break
            values = await _post(page, form, PAGE_DOC, PAGE_NAME, _page_vars(target_id, cursor))
            block = _comments_block(values)
            pages += 1

    sample = [str(c.get("body", {}).get("text") or c.get("body") or "")[:60]
              for c in list(comments.values())[:3]]
    result = {"target_post_id": target_id, "pages": pages, "comments": len(comments),
              "sample": sample}
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"target {target_id}: {len(comments)} unique comments across {pages} pages")
    print(f"sample: {sample}")
    print(f"-> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    bootstrap = sys.argv[1]
    target_id = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else "replay_full.json"
    asyncio.run(main(bootstrap, target_id, out))
