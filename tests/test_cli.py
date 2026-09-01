import json
from crawlfb.cli import _load_pages, _page_id


def test_page_id_strips_trailing_slash():
    assert _page_id("https://www.facebook.com/CotSongGenZ.Page/") == "CotSongGenZ.Page"
    assert _page_id("https://www.facebook.com/cotsongGenZ.YAN") == "cotsongGenZ.YAN"


def test_load_pages_from_dict_list(tmp_path):
    f = tmp_path / "pages.json"
    f.write_text(json.dumps({
        "pages": [
            {"id": "a", "url": "https://x.com/a"},
            {"id": "b", "url": "https://x.com/b"},
        ]
    }), encoding="utf-8")
    assert _load_pages(f) == [("a", "https://x.com/a"), ("b", "https://x.com/b")]


def test_load_pages_from_string_list(tmp_path):
    f = tmp_path / "pages.json"
    f.write_text(json.dumps({"pages": ["https://x.com/c"]}), encoding="utf-8")
    assert _load_pages(f) == [("c", "https://x.com/c")]


def test_load_pages_dict_without_id_falls_back_to_url(tmp_path):
    f = tmp_path / "pages.json"
    f.write_text(json.dumps([{"url": "https://x.com/d"}] ), encoding="utf-8")
    assert _load_pages(f) == [("d", "https://x.com/d")]


def test_load_pages_missing_file(tmp_path):
    assert _load_pages(tmp_path / "nope.json") == []


import asyncio
from crawlfb.cli import _scrape_post_comments
from crawlfb.comments import CommentInterceptor
from crawlfb.config import Config


class _GotoOkPage:
    async def goto(self, *a, **k):
        return None

    async def content(self):
        raise RuntimeError("page closed")


class _EvalBoomPage:
    async def goto(self, *a, **k):
        return None

    async def content(self):
        return "<html></html>"

    async def evaluate(self, *a, **k):
        raise RuntimeError("context destroyed")


def _cfg() -> Config:
    return Config(page_url="https://www.facebook.com/p", output="out.json")


def test_scrape_post_comments_survives_page_content_crash():
    page = _GotoOkPage()
    interceptor = CommentInterceptor(page)
    comments = asyncio.run(_scrape_post_comments(
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg()))
    assert comments == []


def test_scrape_post_comments_survives_evaluate_crash():
    page = _EvalBoomPage()
    interceptor = CommentInterceptor(page)
    comments = asyncio.run(_scrape_post_comments(
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg()))
    assert comments == []
