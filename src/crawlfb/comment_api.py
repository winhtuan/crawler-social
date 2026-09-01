"""Facebook comment GraphQL fetch — root + pagination, no permalink navigation.

Reverse-engineered from the Comet web `/api/graphql/` endpoint. Fetches every
comment for a post by replaying the two RelayModern queries (root + pagination)
in-page via `fetch`, reusing the session form envelope captured from the feed
phase. Preferred over the old per-post `page.goto(permalink)` + scroll path,
which stays as the fallback.
"""
from __future__ import annotations

import base64
import json
import urllib.parse

from crawlfb.comments import (
    _comment_id,
    _is_real_comment,
    _sort_and_cap,
    flatten_comment,
    split_json_values,
)
from crawlfb.intercept import _deep_get

ROOT_DOC = "27046361795040764"
ROOT_NAME = "CommentListComponentsRootQuery"
PAGE_DOC = "27973447728944010"
PAGE_NAME = "CommentsListComponentsPaginationQuery"

# Relay Modern "provider" values FB pins on every comment query. Replaying the
# query without them returns an empty/error payload.
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


def feedback_id(post_id: str) -> str:
    """The Relay `id` FB expects is base64("feedback:<post_id>")."""
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def root_variables(post_id: str) -> dict:
    return {
        "commentsIntentToken": "RANKED_UNFILTERED_CHRONOLOGICAL_REPLIES_INTENT_V1",
        "feedLocation": "POST_PERMALINK_DIALOG",
        "feedbackSource": 2,
        "focusCommentID": None,
        "scale": 1,
        "useDefaultActor": False,
        "id": feedback_id(post_id),
        **_RELAY,
    }


def page_variables(post_id: str, cursor: str) -> dict:
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
        "id": feedback_id(post_id),
        **_RELAY,
    }


def comments_block(values: list) -> dict | None:
    """The `{edges, page_info}` block for the requested post's comments, out of
    a decoded graphql batch (list of JSON values)."""
    for v in values:
        block = _deep_get(
            v, "data", "node", "comment_rendering_instance_for_feed_location", "comments"
        )
        if isinstance(block, dict) and "edges" in block:
            return block
    return None


def comment_nodes(block: dict) -> list[dict]:
    return [
        e["node"]
        for e in (block.get("edges") or [])
        if isinstance(e, dict) and isinstance(e.get("node"), dict)
    ]


def next_cursor(block: dict) -> str | None:
    info = block.get("page_info") or {}
    return info.get("end_cursor") if info.get("has_next_page") else None


async def _post(page, form: dict, doc_id: str, friendly_name: str,
                variables: dict) -> list:
    body = urllib.parse.urlencode(
        {
            **form,
            "doc_id": doc_id,
            "fb_api_req_friendly_name": friendly_name,
            "variables": json.dumps(variables),
        }
    )
    raw = await page.evaluate(_FETCH_JS, body)
    return split_json_values(raw)


# Safety ceiling: a post with ~10 comments/page at 1000 pages is ~10k comments,
# far past any realistic max_comments. Guards against FB returning has_next_page
# with a stable or cycling cursor (rate-limit/error sentinel) which would hang.
_MAX_PAGES = 1000


async def fetch_comments(page, form: dict, post_id: str) -> list[dict]:
    """Fetch all unique comments for `post_id` (page 1 root, then paginate until
    `has_next_page` is false). Returns a list of comment node dicts, deduped by
    `_comment_id`, in first-seen order. Bounded by a max-page and repeated-cursor
    guard so a malformed pagination can never hang the run."""
    comments: dict[str, dict] = {}
    seen_cursors: set[str] = set()
    values = await _post(page, form, ROOT_DOC, ROOT_NAME, root_variables(post_id))
    block = comments_block(values)
    pages = 0
    while block is not None:
        pages += 1
        for node in comment_nodes(block):
            cid = _comment_id(node)
            if cid and cid not in comments:
                comments[cid] = node
        cursor = next_cursor(block)
        if cursor is None or cursor in seen_cursors or pages >= _MAX_PAGES:
            break
        seen_cursors.add(cursor)
        values = await _post(
            page, form, PAGE_DOC, PAGE_NAME, page_variables(post_id, cursor)
        )
        block = comments_block(values)
    return list(comments.values())


def records_from_nodes(nodes: list[dict], post_url: str,
                       max_comments: int) -> list[dict]:
    """Map raw comment nodes to flat records the same way `collect_comments`
    does: drop bare Relay-reference nodes (no body/author), flatten each real
    comment, sort by (likes, date) desc, cap at max_comments (<=0 means no cap),
    and rewrite each comment_url to the post permalink."""
    out: list[dict] = []
    for node in nodes:
        if not _is_real_comment(node):
            continue
        try:
            out.append(flatten_comment(node, post_url))
        except Exception:
            continue
    return _sort_and_cap(out, max_comments)


class GraphQLForm:
    """Captures the session's /api/graphql/ POST form envelope (fb_dtsg, lsd,
    __dyn, __csr, ...) so comment queries can be replayed in-page without
    re-navigating to each permalink.

    The envelope is identical across all graphql query types; only `doc_id`,
    `fb_api_req_friendly_name` and `variables` differ. Matching the comment root
    query's doc_id pins the capture to the first comment request the browser
    fires, whose form is known-good for replaying comment queries.
    """

    def __init__(self):
        self.form: dict | None = None

    def attach(self, page) -> None:
        def on_request(req) -> None:
            if self.form is not None:
                return
            if "/api/graphql/" in req.url and req.method == "POST":
                try:
                    body = req.post_data
                except Exception:
                    return
                if body and ROOT_DOC in body:
                    self.form = dict(urllib.parse.parse_qsl(body))

        page.on("request", on_request)
