import json
from crawlfb.models import Post, Comment


SAMPLE = {
    "facebook_url": "https://www.facebook.com/reel/1443385994361034/",
    "text": "2 đứa hạnh phúc quá dọ",
    "author": "Cột sống GenZ",
    "page_name": "cotsongGenZ.YAN",
    "timestamp": "2026-08-30T07:20:25.000Z",
    "likes": 25,
    "comments": 0,
    "shares": 0,
    "reactions": {"like": 24, "care": 1},
    "top_reactions_count": 2,
    "top_comments": [],
    "comments_list": [],
    "is_video": True,
    "views": 183,
    "hashtags": ["#cotsongGenZ"],
    "attachments": [
        {
            "thumbnail": "https://scontent/thumb.jpg",
            "url": "https://www.facebook.com/reel/1443385994361034/",
            "type": "Video",
            "id": "1443385994361034",
            "ocr_text": None,
        }
    ],
    "post_id": "1122166163469529",
}


def test_post_parses_sample_format():
    post = Post.model_validate(SAMPLE)
    assert post.post_id == "1122166163469529"
    assert post.facebook_url == "https://www.facebook.com/reel/1443385994361034/"
    assert post.author == "Cột sống GenZ"
    assert post.is_video is True
    assert post.views == 183
    assert post.reactions == {"like": 24, "care": 1}
    assert post.top_reactions_count == 2
    assert post.attachments[0].type == "Video"
    assert post.attachments[0].id == "1443385994361034"


def test_post_roundtrip_preserves_sample_keys():
    post = Post.model_validate(SAMPLE)
    dumped = post.model_dump()
    assert set(SAMPLE.keys()) <= set(dumped.keys())


def test_comment_model_shape():
    c = Comment(
        comment_id="1847898512838593",
        text="hay quá",
        author="Van Vo Thanh",
        likes=12,
        date="2026-08-30T05:28:26.000Z",
        threading_depth=0,
        comment_url="https://www.facebook.com/reel/1088606917027756/?comment_id=1847898512838593",
    )
    d = c.model_dump()
    assert set(d.keys()) == {
        "comment_id", "text", "media_type", "media_url", "author", "likes",
        "date", "threading_depth", "comment_url",
    }
