import asyncio
import base64
import json

from crawlfb.comment_api import (
    PAGE_DOC,
    PAGE_NAME,
    ROOT_DOC,
    ROOT_NAME,
    GraphQLForm,
    comment_nodes,
    comments_block,
    feedback_id,
    fetch_comments,
    next_cursor,
    page_variables,
    records_from_nodes,
    root_variables,
)
from crawlfb.comments import _comment_id


def test_feedback_id_encodes_feedback_prefix():
    assert feedback_id("1397751935821992") == base64.b64encode(
        b"feedback:1397751935821992"
    ).decode()


def test_root_variables_shape():
    v = root_variables("123")
    assert v["id"] == feedback_id("123")
    assert v["feedbackSource"] == 2
    assert v["focusCommentID"] is None
    assert v["commentsIntentToken"] == "RANKED_UNFILTERED_CHRONOLOGICAL_REPLIES_INTENT_V1"
    assert v["feedLocation"] == "POST_PERMALINK_DIALOG"
    # root query has no pagination cursor fields
    assert "commentsAfterCursor" not in v
    assert v["__relay_internal__pv__IsWorkUserrelayprovider"] is False


def test_page_variables_shape():
    v = page_variables("123", "CURSOR")
    assert v["id"] == feedback_id("123")
    assert v["commentsAfterCursor"] == "CURSOR"
    assert v["commentsAfterCount"] == -1
    assert v["targetDialect"] is None
    # pagination query drops feedbackSource, adds the cursor fields
    assert "feedbackSource" not in v


def _comments_resp(edges, has_next, end_cursor):
    return {
        "data": {"node": {"comment_rendering_instance_for_feed_location": {
            "comments": {
                "edges": edges,
                "page_info": {"has_next_page": has_next, "end_cursor": end_cursor},
            }
        }}}
    }


def _edge(cid):
    return {"node": {
        "id": f"comment:{cid}",
        "legacy_fbid": cid,
        "body": {"text": f"c{cid}"},
        "author": {"name": "x"},
    }}


def test_comments_block_and_nodes_and_cursor():
    block = comments_block([_comments_resp([_edge("1"), _edge("2")], True, "C")])
    assert block is not None
    assert comment_nodes(block) == [_edge("1")["node"], _edge("2")["node"]]
    assert next_cursor(block) == "C"


def test_comments_block_none_when_path_missing():
    assert comments_block([{"data": {"node": {}}}]) is None


def test_next_cursor_none_when_no_next_page():
    block = comments_block([_comments_resp([], False, "C")])
    assert next_cursor(block) is None


class FakePage:
    def __init__(self, responses):
        self._responses = list(responses)
        self.bodies = []

    async def evaluate(self, js, body):
        self.bodies.append(body)
        return self._responses.pop(0)


def test_fetch_comments_paginates_and_dedupes():
    # root: comments 1,2 -> cursor C1; page C1: 2,3 -> C2; page C2: 3 -> no next.
    responses = [
        json.dumps(_comments_resp([_edge("1"), _edge("2")], True, "C1")),
        json.dumps(_comments_resp([_edge("2"), _edge("3")], True, "C2")),
        json.dumps(_comments_resp([_edge("3")], False, "C3")),
    ]
    page = FakePage(responses)
    form = {"fb_dtsg": "x", "av": "1"}

    comments = asyncio.run(fetch_comments(page, form, "123"))

    assert sorted(_comment_id(c) for c in comments) == ["1", "2", "3"]
    assert len(page.bodies) == 3
    # second call is the pagination query with the first page's cursor
    import urllib.parse
    second = dict(urllib.parse.parse_qsl(page.bodies[1]))
    assert second["doc_id"] == PAGE_DOC
    assert second["fb_api_req_friendly_name"] == PAGE_NAME
    assert json.loads(second["variables"])["commentsAfterCursor"] == "C1"


def test_fetch_comments_doc_ids():
    # smoke: the reverse-engineered doc ids are pinned so a regression is loud
    assert ROOT_DOC == "27046361795040764"
    assert ROOT_NAME == "CommentListComponentsRootQuery"
    assert PAGE_DOC == "27973447728944010"
    assert PAGE_NAME == "CommentsListComponentsPaginationQuery"


def _liked_node(cid, likes, created):
    node = _edge(cid)["node"]
    node["comment_action_links"] = [{"comment": {"feedback": {"reactors": {"count": likes}}}}]
    node["created_time"] = created
    return node


def test_records_from_nodes_flattens_sorts_and_caps():
    nodes = [
        _liked_node("1", likes=0, created=100),
        _liked_node("2", likes=5, created=200),
        _liked_node("3", likes=9, created=300),
    ]
    records = records_from_nodes(nodes, "https://fb.com/post", max_comments=2)
    # sorted by likes desc, capped at 2 -> the two most-liked
    assert [r["comment_id"] for r in records] == ["3", "2"]
    assert records[0]["author"] == "x"
    assert records[0]["text"] == "c3"
    assert records[0]["comment_url"] == "https://fb.com/post?comment_id=3"
    # no cap when max_comments <= 0
    assert len(records_from_nodes(nodes, "u", 0)) == 3


def test_records_from_nodes_drops_bare_relay_refs():
    bare = {"id": "comment:123_456"}  # no legacy_fbid/body/author
    real = _edge("9")["node"]
    records = records_from_nodes([bare, real], "https://fb.com/post", 10)
    assert [r["comment_id"] for r in records] == ["9"]


def test_fetch_comments_breaks_on_repeated_cursor():
    # has_next_page true but end_cursor never advances -> must terminate
    responses = [
        json.dumps(_comments_resp([_edge("1")], True, "C1")),
        json.dumps(_comments_resp([_edge("1")], True, "C1")),
    ]
    page = FakePage(responses)
    comments = asyncio.run(fetch_comments(page, {"fb_dtsg": "x"}, "123"))
    assert [_comment_id(c) for c in comments] == ["1"]
    assert len(page.bodies) == 2


class _FakeReq:
    def __init__(self, url, method, post_data=None):
        self.url = url
        self.method = method
        self._post_data = post_data

    @property
    def post_data(self):
        if self._post_data is None:
            raise Exception("no post data")
        return self._post_data


class _FakePage:
    def __init__(self):
        self.handler = None

    def on(self, event, handler):
        self.handler = handler


def test_graphql_form_captures_root_query_envelope():
    page = _FakePage()
    cap = GraphQLForm()
    cap.attach(page)

    # non-graphql request: ignored
    page.handler(_FakeReq("https://fb.com/posts/", "GET"))
    assert cap.form is None
    # graphql request, wrong doc_id: ignored
    page.handler(_FakeReq("https://fb.com/api/graphql/", "POST",
                          "doc_id=111&fb_api_req_friendly_name=FeedQuery&variables={}"))
    assert cap.form is None
    # the comment root query: captured, then further requests are ignored
    body = f"doc_id={ROOT_DOC}&fb_api_req_friendly_name=CommentListComponentsRootQuery&fb_dtsg=abc&variables=%7B%7D"
    page.handler(_FakeReq("https://fb.com/api/graphql/", "POST", body))
    assert cap.form == {"doc_id": ROOT_DOC,
                        "fb_api_req_friendly_name": "CommentListComponentsRootQuery",
                        "fb_dtsg": "abc",
                        "variables": "{}"}
    # a later request does not overwrite the captured form
    page.handler(_FakeReq("https://fb.com/api/graphql/", "POST", "doc_id=999&x=1"))
    assert cap.form["doc_id"] == ROOT_DOC
