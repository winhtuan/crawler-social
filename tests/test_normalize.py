import json
from pathlib import Path
from crawlfb.normalize import normalize_post
from crawlfb.models import Post

RAW = {
    "post_id": "1360424439627222",
    "page_id": "100069790373758",
    "author_id": "100069790373758",
    "author_name": "Cột Sống Gen Z",
    "author_profile_url": "https://www.facebook.com/100069790373758",
    "author_profile_pic": "",
    "text": "Tỏ tình xong hắc “hoá” luôn\n\n#cotsonggenzpage",
    "created_time_iso": "2026-08-10T08:40:48.000Z",
    "created_unix": 1786351248,
    "reaction_counts": {"LIKE": 58, "LOVE": 1, "HAHA": 69, "SAD": 9},
    "comment_count": 1,
    "share_count": 1,
    "permalink_url": "https://www.facebook.com/CotSongGenZ.Page/posts/pfbid0Fjq",
    "attachments": [],
    "is_video": False,
    "views": 0,
}


def test_normalize_post_maps_all_fields():
    post = normalize_post(RAW, "CotSongGenZ.Page")
    assert post.post_id == "1360424439627222"
    assert post.facebook_url == RAW["permalink_url"]
    assert post.author == "Cột Sống Gen Z"
    assert post.page_name == "CotSongGenZ.Page"
    assert post.timestamp == "2026-08-10T08:40:48.000Z"
    assert post.likes == 137  # 58 + 1 + 69 + 9
    assert post.comments == 1
    assert post.shares == 1
    assert post.reactions == {"like": 58, "love": 1, "haha": 69, "sad": 9}
    assert post.top_reactions_count == 4
    assert post.is_video is False
    assert post.views == 0
    assert post.hashtags == ["#cotsonggenzpage"]
    assert post.comments_list == []
    assert post.top_comments == []


def test_normalize_likes_sums_all_reaction_types():
    raw = dict(RAW, reaction_counts={
        "LIKE": 58, "LOVE": 1, "HAHA": 69, "SAD": 9, "CARE": 5, "WOW": 2, "ANGRY": 3,
    })
    post = normalize_post(raw, "CotSongGenZ.Page")
    assert post.likes == 58 + 1 + 69 + 9 + 5 + 2 + 3
    assert post.top_reactions_count == 7


def test_normalize_post_attaches_comments_and_top_comment():
    comments = [
        {"comment_id": "1", "text": "hay", "author": "A", "likes": 5,
         "date": "2026-08-10T09:00:00.000Z", "threading_depth": 0,
         "comment_url": "https://x/?comment_id=1"},
        {"comment_id": "2", "text": "ok", "author": "B", "likes": 2,
         "date": "2026-08-10T09:01:00.000Z", "threading_depth": 0,
         "comment_url": "https://x/?comment_id=2"},
    ]
    post = normalize_post(RAW, "CotSongGenZ.Page", comments)
    assert [c.comment_id for c in post.comments_list] == ["1", "2"]
    assert len(post.top_comments) == 1
    assert post.top_comments[0].text == "hay"
    assert post.top_comments[0].author == "A"
    assert post.top_comments[0].likes == 5


# --- Fixture-driven extraction + flattening ---

from crawlfb.intercept import extract_stories, flatten, split_json_values, is_reel

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "feed_graphql.json").read_text(encoding="utf-8")
)


def test_extract_stories_finds_at_least_one():
    nodes = []
    for entry in FIXTURE:
        nodes += extract_stories(entry["body"])
    assert len(nodes) >= 1
    assert all("post_id" in flatten(n, "", "") for n in nodes)


def test_split_json_values_splits_concatenated():
    assert split_json_values('{"a":1}\n{"b":2}') == [{"a": 1}, {"b": 2}]
    assert len(split_json_values('{"a":1}   \n  {"b":2}\n')) == 2


def test_extract_stories_dedupes_in_order():
    nodes = extract_stories(FIXTURE[0]["body"])
    assert len(nodes) == 3
    assert len({n["post_id"] for n in nodes}) == len(nodes)
    all_nodes = []
    for entry in FIXTURE:
        all_nodes += extract_stories(entry["body"])
    assert len(all_nodes) == 6
    assert len({n["post_id"] for n in all_nodes}) == 6


def test_flatten_extracts_attachments():
    all_nodes = [n for entry in FIXTURE for n in extract_stories(entry["body"])]
    story = next(n for n in all_nodes if flatten(n, "", "")["attachments"])
    att = flatten(story, "", "")["attachments"][0]
    assert att["type"] in ("Photo", "Video")
    assert att["id"]
    if att["type"] == "Photo":
        assert att["thumbnail"].startswith("https://scontent")
        assert att["url"].startswith("https://www.facebook.com/photo/")
    else:
        assert att["url"].startswith("https://www.facebook.com/reel/")


def test_flatten_extracts_video_views():
    all_nodes = [n for entry in FIXTURE for n in extract_stories(entry["body"])]
    video = next(n for n in all_nodes if flatten(n, "", "")["is_video"])
    flat = flatten(video, "", "")
    assert flat["is_video"] is True
    assert flat["views"] > 0


def test_flatten_maps_care_reaction():
    all_nodes = [n for entry in FIXTURE for n in extract_stories(entry["body"])]
    care = next(n for n in all_nodes if flatten(n, "", "").get("reaction_counts", {}).get("CARE"))
    assert care["post_id"] == "1377401131262886"
    assert flatten(care, "", "")["reaction_counts"]["CARE"] == 5


def test_flatten_share_count_non_int_degrades():
    node = {
        "post_id": "1", "creation_time": 0, "actors": [{"id": "1", "name": "a"}],
        "comet_sections": {"feedback": {"story": {"story_ufi_container": {"story": {
            "feedback_context": {"feedback_target_with_context": {
                "comet_ufi_summary_and_actions_renderer": {"feedback": {
                    "share_count": {"count": {"bad": True}},
                    "top_reactions": {"edges": []},
                }}
            }}
        }}}}},
    }
    flat = flatten(node, "", "")
    assert flat["share_count"] == 0


def _node_with_fb(fb):
    return {
        "post_id": "1", "creation_time": 0, "actors": [{"id": "1", "name": "a"}],
        "comet_sections": {"feedback": {"story": {"story_ufi_container": {"story": {
            "feedback_context": {"feedback_target_with_context": {
                "comet_ufi_summary_and_actions_renderer": {"feedback": fb},
            }}
        }}}}},
    }


def test_is_reel_detects_reel_permalink():
    assert is_reel({"permalink_url": "https://www.facebook.com/reel/1728723268179986/"}) is True
    assert is_reel({"permalink_url": "https://www.facebook.com/CotSongGenZ.Page/posts/pfbid0vzZ/"}) is False
    assert is_reel({}) is False


def test_flatten_logged_in_comment_and_share_count():
    # Logged-in /posts/ feed: counts live under adaptive_ufi_action_renderers,
    # not the logged-out comments_count_summary_renderer path.
    fb = {
        "adaptive_ufi_action_renderers": [
            {"feedback": {"reaction_count": {"count": 375}}},
            {"feedback": {"comment_rendering_instance": {"comments": {"total_count": 12}}}},
            {"feedback": {"share_count": {"count": 7}}},
        ],
        "top_reactions": {"edges": []},
    }
    flat = flatten(_node_with_fb(fb), "", "")
    assert flat["comment_count"] == 12
    assert flat["share_count"] == 7
