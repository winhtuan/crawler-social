import json
from pathlib import Path
from crawlfb.models import Post

REF = json.loads(
    (Path(__file__).parent.parent / "CotSongGenZ_Page.json").read_text(encoding="utf-8")
)[0]

def test_post_parses_reference_json():
    post = Post.model_validate(REF)
    assert post.postId == "1360424439627222"
    assert post.pageName == "CotSongGenZ.Page"
    assert post.text.startswith("Tỏ tình xong hắc")
    assert post.likes == 137
    assert post.reactionHahaCount == 69
    assert post.reactionLikeCount == 58
    assert post.reactionSadCount == 9
    assert post.reactionLoveCount == 1
    assert post.topReactionsCount == 4
    assert post.comments == 1
    assert post.shares == 1
    assert post.paidPartnership is False
    assert post.user.id == "100069790373758"
    assert post.user.name == "Cột Sống Gen Z"

def test_post_roundtrip_preserves_top_level_keys():
    post = Post.model_validate(REF)
    dumped = post.model_dump()
    assert set(dumped.keys()) == set(REF.keys())

def test_media_parses_reference_json():
    post = Post.model_validate(REF)
    assert len(post.media) == 1
    m = post.media[0]
    assert m.__typename == "Photo"
    assert m.__isMedia == "Photo"
    assert m.photo_image.uri.startswith("https://scontent")
    assert m.photo_image.height == 526
    assert m.photo_image.width == 526
    assert "May be an image of text" in m.ocrText
