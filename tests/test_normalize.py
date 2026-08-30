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

from crawlfb.intercept import extract_stories, flatten

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "feed_graphql.json").read_text(encoding="utf-8")
)

def test_extract_stories_finds_at_least_one():
    nodes = []
    for entry in FIXTURE:
        nodes += extract_stories(entry["body"])
    assert len(nodes) >= 1
    assert all("post_id" in flatten(n, "", "") for n in nodes)

def test_flatten_roundtrip_matches_reference_shape():
    post = normalize_post(flatten(extract_stories(FIXTURE[0]["body"])[0], "", "CotSongGenZ.Page"),
                          "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert set(post.model_dump().keys()) == set(Post.model_validate({}).model_dump().keys())
