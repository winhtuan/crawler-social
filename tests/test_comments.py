import base64

from crawlfb.comments import (
    flatten_comment,
    extract_comments,
    extract_comments_from_html,
    _comment_id,
    _is_real_comment,
    _comment_post_id,
    _reel_to_watch,
    CommentInterceptor,
    collect_comments,
)


def test_comment_id_prefers_legacy_fbid_then_strips_prefix():
    assert _comment_id({"legacy_fbid": "1781129452904905"}) == "1781129452904905"
    assert _comment_id({"legacy_comment_id": "1847898512838593"}) == "1847898512838593"
    assert _comment_id({"comment_id": "2153575655192878"}) == "2153575655192878"
    assert _comment_id({"id": "100069790373758_1847898512838593"}) == "1847898512838593"


def _node(**over):
    node = {
        "__typename": "Comment",
        "legacy_fbid": "1847898512838593",
        "id": "Y29tbWVudDoxMTIyMzY1NjYzNDQ5NTc5XzE4NDc4OTg1MTI4Mzg1OTM=",
        "body": {"text": "hay quá", "ranges": []},
        "author": {"name": "Van Vo Thanh"},
        "created_time": 1788066200,
        "depth": 0,
        "comment_action_links": [
            {"comment": {"feedback": {"reactors": {"count": 12, "is_empty": False}}}},
        ],
    }
    node.update(over)
    return node


def test_flatten_comment_maps_real_fields():
    c = flatten_comment(_node(), "https://www.facebook.com/reel/1088606917027756/")
    assert c["comment_id"] == "1847898512838593"
    assert c["text"] == "hay quá"
    assert c["author"] == "Van Vo Thanh"
    assert c["likes"] == 12
    assert c["date"].endswith("Z")
    assert c["threading_depth"] == 0
    assert c["comment_url"] == "https://www.facebook.com/reel/1088606917027756/?comment_id=1847898512838593"


def test_flatten_comment_body_string_and_depth():
    node = _node(body="plain text", depth=1)
    c = flatten_comment(node, "https://x/")
    assert c["text"] == "plain text"
    assert c["threading_depth"] == 1


def test_flatten_comment_text_has_empty_media_marker():
    c = flatten_comment(_node(), "https://x/")
    assert c["media_type"] == ""
    assert c["media_url"] == ""


def test_flatten_comment_marks_video_attachment():
    node = _node(body=None)
    node["attachments"] = [{
        "style_list": ["video_inline", "video"],
        "style_type_renderer": {"attachment": {
            "url": "https://www.facebook.com/bence.sarusikiss/videos/952536887906156/",
            "target": {"__typename": "Video", "id": "952536887906156"},
            "media": {"__typename": "Video"},
        }},
    }]
    c = flatten_comment(node, "https://x/")
    assert c["text"] == ""
    assert c["media_type"] == "video"
    assert c["media_url"] == "https://www.facebook.com/bence.sarusikiss/videos/952536887906156/"


def test_flatten_comment_marks_image_attachment():
    node = _node(body=None)
    node["attachments"] = [{
        "style_list": ["photo"],
        "style_type_renderer": {"attachment": {
            "target": {"__typename": "Photo"},
            "media": {"__typename": "Photo", "uri": "https://scontent/img.jpg"},
        }},
    }]
    c = flatten_comment(node, "https://x/")
    assert c["media_type"] == "image"
    assert c["media_url"] == "https://scontent/img.jpg"


def test_flatten_comment_marks_sticker_field():
    node = _node(body=None)
    node["sticker"] = {"url": "https://scontent/sticker.png"}
    c = flatten_comment(node, "https://x/")
    assert c["media_type"] == "sticker"
    assert c["media_url"] == "https://scontent/sticker.png"


def test_flatten_comment_likes_falls_back_to_count_reduced():
    node = _node(comment_action_links=[])
    node["feedback"] = {"reactors": {"count_reduced": "634"}}
    c = flatten_comment(node, "https://x/")
    assert c["likes"] == 634


def test_extract_comments_dedupes_in_order():
    batch = [
        _node(),
        _node(),
        {"wrapper": _node(legacy_fbid="2", body={"text": "b"})},
        {"__typename": "Story", "post_id": "9"},
    ]
    comments = extract_comments(batch)
    ids = [flatten_comment(c, "https://x/")["comment_id"] for c in comments]
    assert ids == ["1847898512838593", "2"]


def test_extract_comments_from_html_finds_ssr_script():
    payload = '{"require":[["x",null,null,{"data":{' \
              '"__typename":"Comment","legacy_fbid":"123","body":{"text":"c"},' \
              '"author":{"name":"A"},"created_time":1,"depth":0}}]]}'
    html = f'<script type="application/json" data-sjs="">{payload}</script>'
    nodes = extract_comments_from_html(html)
    assert [flatten_comment(n, "https://x/")["comment_id"] for n in nodes] == ["123"]


def test_is_real_comment_accepts_graphql_wrapped_no_typename():
    # Feed / "view more" graphql wraps comments as {"comment": {...}} with no
    # __typename; must still be recognized.
    node = {"legacy_fbid": "1049626554740220", "body": {"text": "hi"},
            "author": {"name": "A"}, "depth": 0}
    assert _is_real_comment(node) is True


def test_is_real_comment_skips_bare_relay_ref():
    assert _is_real_comment({"id": "Y29tbWVudDoxMTE5XzEwNDk="}) is False
    assert _is_real_comment({"__typename": "Comment", "id": "Y29tbWVudDoxMTE5XzEwNDk="}) is False


def test_comment_post_id_decodes_relay_id():
    # base64("comment:1119751413711004_1049626554740220")
    node = {"id": "Y29tbWVudDoxMTE5NzUxNDEzNzExMDA0XzEwNDk2MjY1NTQ3NDAyMjA="}
    assert _comment_post_id(node) == "1119751413711004"


def test_comment_post_id_plain_underscore():
    assert _comment_post_id({"id": "comment:1122_1781"}) == "1122"
    assert _comment_post_id({"id": "1122_1781"}) == "1122"


def test_reel_to_watch_rewrites_reel_url():
    assert _reel_to_watch("https://www.facebook.com/reel/910068878409278/") == \
        "https://www.facebook.com/watch/?v=910068878409278"


def test_reel_to_watch_leaves_non_reel_untouched():
    assert _reel_to_watch("https://www.facebook.com/x/posts/pfbid02abc/") == \
        "https://www.facebook.com/x/posts/pfbid02abc/"
    assert _reel_to_watch("https://www.facebook.com/x/videos/910068878409278/") == \
        "https://www.facebook.com/x/videos/910068878409278/"


def test_collect_comments_caps_at_max():
    inter = CommentInterceptor(None)
    for i in range(5):
        inter.add_nodes([_node(legacy_fbid=str(i), body={"text": f"c{i}"})])
    got = collect_comments(inter, "https://x/", "1122365663449579", max_comments=2)
    assert [c["comment_id"] for c in got] == ["0", "1"]


def test_collect_comments_no_cap_when_max_nonpositive():
    inter = CommentInterceptor(None)
    for i in range(5):
        inter.add_nodes([_node(legacy_fbid=str(i), body={"text": f"c{i}"})])
    got = collect_comments(inter, "https://x/", "1122365663449579", max_comments=0)
    assert len(got) == 5


def test_collect_comments_sorts_most_liked_first():
    inter = CommentInterceptor(None)
    inter.add_nodes([_node(legacy_fbid="1", body={"text": "low"},
                           comment_action_links=[{"comment": {"feedback": {"reactors": {"count": 2}}}}])])
    inter.add_nodes([_node(legacy_fbid="2", body={"text": "high"},
                           comment_action_links=[{"comment": {"feedback": {"reactors": {"count": 99}}}}])])
    inter.add_nodes([_node(legacy_fbid="3", body={"text": "mid"},
                           comment_action_links=[{"comment": {"feedback": {"reactors": {"count": 5}}}}])])
    got = collect_comments(inter, "https://x/", "1122365663449579", max_comments=0)
    assert [c["comment_id"] for c in got] == ["2", "3", "1"]


def test_add_nodes_buckets_ssr_html_comment_by_relay_id():
    # Permalink SSR comments (data-sjs) carry a base64 Relay id alongside
    # legacy_fbid; add_nodes must decode the post id and bucket the comment so
    # comments_for_post(post_id) returns it — the path Phase 2 relies on.
    relay = base64.b64encode(
        b"comment:1122365663449579_1781129452904905"
    ).decode("ascii")
    node = {
        "__typename": "Comment",
        "legacy_fbid": "1781129452904905",
        "id": relay,
        "body": {"text": "ssr comment"},
        "author": {"name": "A"},
        "created_time": 1,
        "depth": 0,
    }
    inter = CommentInterceptor(None)
    inter.add_nodes([node])
    got = inter.comments_for_post("1122365663449579")
    assert got["1781129452904905"]["text"] == "ssr comment"


def test_comments_for_post_isolates_by_post():
    # Two posts, each with one comment — comments_for_post must return only the
    # owning post's comments (no cross-post leakage from the by_post bucket).
    inter = CommentInterceptor(None)
    inter.add_nodes([_node(
        legacy_fbid="c1", id="comment:111_1001", body={"text": "post 1"},
    )])
    inter.add_nodes([_node(
        legacy_fbid="c2", id="comment:222_2002", body={"text": "post 2"},
    )])
    assert [c["comment_id"] for c in inter.comments_for_post("111").values()] == ["c1"]
    assert [c["comment_id"] for c in inter.comments_for_post("222").values()] == ["c2"]
    assert inter.comments_for_post("999") == {}
