from crawlfb.recent import (
    _normalize_apify,
    _normalize_scrapecreators,
    existing_post_ids,
    fetch_recent,
)


def test_normalize_scrapecreators_maps_fields():
    p = {
        "id": "123",
        "permalink": "https://www.facebook.com/SomePage/posts/123",
        "text": "hello #world",
        "author": {"name": "Alice"},
        "publishTime": 1700000000,
        "reactionCount": 10,
        "commentCount": 3,
        "videoViewCount": 0,
        "topComments": [{"text": "c1", "author": {"name": "Bob"}}],
    }
    post = _normalize_scrapecreators(p, "SomePage")
    assert post.post_id == "123"
    assert post.facebook_url == "https://www.facebook.com/SomePage/posts/123"
    assert post.text == "hello #world"
    assert post.author == "Alice"
    assert post.page_name == "SomePage"
    assert post.likes == 10
    assert post.comments == 3
    assert post.hashtags == ["#world"]
    assert post.is_video is False
    assert len(post.top_comments) == 1
    assert post.top_comments[0].text == "c1"
    assert post.top_comments[0].author == "Bob"


def test_normalize_scrapecreators_video_marks_attachment():
    p = {
        "id": "1",
        "url": "https://www.facebook.com/SomePage/videos/1",
        "text": "",
        "author": {"name": "A"},
        "publishTime": 0,
        "videoDetails": {
            "thumbnailUrl": "t.jpg",
            "hdUrl": "v.mp4",
        },
        "topComments": [],
    }
    post = _normalize_scrapecreators(p, "SomePage")
    assert post.is_video is True
    assert post.attachments[0].type == "Video"
    assert post.attachments[0].url == "v.mp4"
    assert post.attachments[0].thumbnail == "t.jpg"


def test_normalize_apify_maps_reactions_and_media():
    item = {
        "postId": "456",
        "url": "https://www.facebook.com/SomePage/posts/456",
        "text": "video post",
        "user": {"name": "Carol"},
        "likes": 5,
        "comments": 2,
        "shares": 1,
        "reactionLikeCount": 4,
        "reactionLoveCount": 1,
        "reactionCareCount": 0,
        "reactionWowCount": 2,
        "reactionHahaCount": 0,
        "topReactionsCount": 2,
        "time": "2026-01-01T00:00:00.000Z",
        "viewsCount": 100,
        "media": [{
            "thumbnail": "t.jpg",
            "url": "v.mp4",
            "__typename": "Video",
            "id": "v1",
            "ocrText": None,
        }],
    }
    post = _normalize_apify(item, "SomePage")
    assert post.post_id == "456"
    assert post.author == "Carol"
    assert post.reactions == {"like": 4, "love": 1, "wow": 2}
    assert post.is_video is True
    assert post.views == 100
    assert post.attachments[0].type == "Video"
    assert post.attachments[0].id == "v1"


def test_normalize_apify_zero_reactions_omitted():
    item = {
        "postId": "1",
        "url": "https://x",
        "text": "",
        "user": {},
        "reactionLikeCount": 0,
        "reactionLoveCount": 0,
        "reactionCareCount": 0,
        "reactionWowCount": 0,
        "reactionHahaCount": 0,
    }
    post = _normalize_apify(item, "P")
    assert post.reactions == {}


def _scrape_post():
    return {
        "id": "s1",
        "permalink": "https://www.facebook.com/SomePage/posts/s1",
        "text": "scrape post",
        "author": {"name": "S"},
        "publishTime": 1700000000,
        "reactionCount": 1,
        "commentCount": 0,
        "videoViewCount": 0,
        "topComments": [],
    }


def _apify_item():
    return {
        "postId": "a1",
        "url": "https://www.facebook.com/SomePage/posts/a1",
        "text": "apify post",
        "user": {"name": "A"},
        "likes": 0,
        "comments": 0,
    }


def test_fetch_recent_scrapecreators_success(monkeypatch):
    def fake_http(url, **kw):
        return {"success": True, "posts": [_scrape_post()], "cursor": None}

    monkeypatch.setattr("crawlfb.recent._http_json", fake_http)
    posts = fetch_recent(
        "https://www.facebook.com/SomePage",
        scrape_key="k", base_url="http://scrape.example", limit=3,
    )
    assert [p.post_id for p in posts] == ["s1"]


def test_fetch_recent_retries_scrapecreators_once(monkeypatch):
    calls = {"n": 0}

    def fake_http(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient network error")
        return {"success": True, "posts": [_scrape_post()], "cursor": None}

    monkeypatch.setattr("crawlfb.recent._http_json", fake_http)
    posts = fetch_recent(
        "https://www.facebook.com/SomePage",
        scrape_key="k", base_url="http://scrape.example", limit=3, max_attempts=2,
    )
    assert [p.post_id for p in posts] == ["s1"]
    assert calls["n"] == 2


def test_fetch_recent_falls_back_to_apify(monkeypatch):
    urls = []

    def fake_http(url, **kw):
        urls.append(url)
        if "/v1/facebook/profile/posts" in url:
            raise OSError("scrapecreators down")
        return [_apify_item()]

    monkeypatch.setattr("crawlfb.recent._http_json", fake_http)
    posts = fetch_recent(
        "https://www.facebook.com/SomePage",
        scrape_key="k", apify_token="t", base_url="http://scrape.example", limit=3,
    )
    assert [p.post_id for p in posts] == ["a1"]
    assert any("/v1/facebook/profile/posts" in u for u in urls)
    assert any("apify" in u for u in urls)


def test_fetch_recent_empty_without_keys(monkeypatch):
    def boom(url, **kw):
        raise AssertionError("should not be called without keys")

    monkeypatch.setattr("crawlfb.recent._http_json", boom)
    monkeypatch.delenv("SCRAPE_CREATORS_API_KEY", raising=False)
    monkeypatch.delenv("APIFY_API_TOKEN", raising=False)
    assert fetch_recent("https://www.facebook.com/SomePage") == []


def test_existing_post_ids_reads_ids(tmp_path):
    f = tmp_path / "out.json"
    f.write_text(
        '[{"post_id": "1"}, {"post_id": "2"}, {"no_id": true}, "junk"]',
        encoding="utf-8",
    )
    assert existing_post_ids(f) == {"1", "2"}


def test_existing_post_ids_missing_or_corrupt(tmp_path):
    assert existing_post_ids(tmp_path / "nope.json") == set()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert existing_post_ids(bad) == set()
