import base64
import json
from pathlib import Path
from crawlfb.normalize import normalize_post, feedback_id, top_level_url
from crawlfb.models import Post

RAW = {
    "post_id": "1360424439627222",
    "page_id": "100069790373758",
    "author_id": "100069790373758",
    "author_name": "Cột Sống Gen Z",
    "author_profile_url": "https://www.facebook.com/100069790373758",
    "author_profile_pic": "https://scontent/avatar.png",
    "text": "Tỏ tình xong hắc “hoá” luôn\n\n#cotsonggenzpage",
    "created_time_iso": "2026-08-10T08:40:48.000Z",
    "created_unix": 1786351248,
    "reaction_counts": {"LIKE": 58, "LOVE": 1, "HAHA": 69, "SAD": 9},
    "comment_count": 1,
    "share_count": 1,
    "permalink_url": "https://www.facebook.com/CotSongGenZ.Page/posts/pfbid0Fjq",
    "media": [],
}

def test_feedback_id_is_base64_of_feedback_colon_postid():
    expected = base64.b64encode(b"feedback:1360424439627222").decode()
    assert feedback_id("1360424439627222") == expected

def test_top_level_url_is_computed():
    assert top_level_url("100069790373758", "1360424439627222") == \
        "https://www.facebook.com/100069790373758/posts/1360424439627222"

def test_normalize_post_maps_all_fields():
    post = normalize_post(RAW, "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert post.postId == "1360424439627222"
    assert post.feedbackId == feedback_id("1360424439627222")
    assert post.topLevelUrl == top_level_url("100069790373758", "1360424439627222")
    assert post.facebookId == "100069790373758"
    assert post.user.name == "Cột Sống Gen Z"
    assert post.likes == 137
    assert post.topReactionsCount == 4
    assert post.reactionHahaCount == 69
    assert post.reactionLikeCount == 58
    assert post.reactionSadCount == 9
    assert post.reactionLoveCount == 1
    assert post.inputUrl == "https://www.facebook.com/CotSongGenZ.Page/"
    assert post.facebookUrl == "https://www.facebook.com/CotSongGenZ.Page/"

# --- Fixture-driven extraction + flattening (plan Task 4, steps 5-6) ---

from crawlfb.intercept import extract_stories, flatten, split_json_values

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "feed_graphql.json").read_text(encoding="utf-8")
)

def test_extract_stories_finds_at_least_one():
    nodes = []
    for entry in FIXTURE:
        nodes += extract_stories(entry["body"])
    assert len(nodes) >= 1
    assert all("post_id" in flatten(n, "", "") for n in nodes)

REF = json.loads(
    (Path(__file__).parent.parent / "CotSongGenZ_Page.json").read_text(encoding="utf-8")
)[0]

def test_flatten_roundtrip_matches_reference_shape():
    post = normalize_post(flatten(extract_stories(FIXTURE[0]["body"])[0], "", "CotSongGenZ.Page"),
                          "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert set(REF.keys()) <= set(post.model_dump().keys())

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

def test_flatten_extracts_media():
    all_nodes = [n for entry in FIXTURE for n in extract_stories(entry["body"])]
    story = next(n for n in all_nodes if flatten(n, "", "")["media"])
    media = flatten(story, "", "")["media"][0]
    assert media["__typename"] == "Photo"
    assert media["photo_image"]["uri"].startswith("https://scontent")
    assert media["photo_image"]["height"] > 0
    assert media["photo_image"]["width"] > 0
    assert isinstance(media["id"], str) and media["id"]
    assert isinstance(media["url"], str) and media["url"]
    assert media["feedback"]["id"]

def test_flatten_maps_care_reaction():
    all_nodes = [n for entry in FIXTURE for n in extract_stories(entry["body"])]
    care = next(n for n in all_nodes if flatten(n, "", "").get("reaction_counts", {}).get("CARE"))
    assert care["post_id"] == "1377401131262886"
    assert flatten(care, "", "")["reaction_counts"]["CARE"] == 5

def test_normalize_likes_sums_all_reaction_types():
    raw = dict(RAW, reaction_counts={"LIKE": 58, "LOVE": 1, "HAHA": 69, "SAD": 9,
                                     "CARE": 5, "WOW": 2, "ANGRY": 3})
    post = normalize_post(raw, "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert post.likes == 58 + 1 + 69 + 9 + 5 + 2 + 3
    assert post.topReactionsCount == 7

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
