import json
from argparse import Namespace
from crawlfb.cli import _load_pages, _page_id, _resolve_tuning


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
from crawlfb.comment_api import GraphQLForm
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
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg(), GraphQLForm()))
    assert comments == []


def test_scrape_post_comments_survives_evaluate_crash():
    page = _EvalBoomPage()
    interceptor = CommentInterceptor(page)
    comments = asyncio.run(_scrape_post_comments(
        page, interceptor, "https://www.facebook.com/p/posts/1", "1", _cfg(), GraphQLForm()))
    assert comments == []


from crawlfb.cli import _rotate_proxy_script


def test_rotate_proxy_script_path_is_repo_tools():
    p = _rotate_proxy_script()
    assert p.name == "rotate_proxy.py"
    assert p.exists()


def test_resolve_tuning_cli_over_env(monkeypatch):
    monkeypatch.setenv("FB_MAX_POSTS", "10")
    monkeypatch.setenv("FB_DELAY_BASE", "9.5")
    args = Namespace(max_posts=25, delay_base=1.5, delay_jitter=None)
    assert _resolve_tuning(args) == (25, 1.5, 2.0)


def test_resolve_tuning_env_fallback(monkeypatch):
    monkeypatch.setenv("FB_MAX_POSTS", "12")
    monkeypatch.setenv("FB_DELAY_BASE", "7.0")
    monkeypatch.setenv("FB_DELAY_JITTER", "3.0")
    args = Namespace(max_posts=None, delay_base=None, delay_jitter=None)
    assert _resolve_tuning(args) == (12, 7.0, 3.0)


def test_resolve_tuning_defaults_and_bad_env(monkeypatch):
    monkeypatch.setenv("FB_MAX_POSTS", "notanumber")
    monkeypatch.delenv("FB_DELAY_BASE", raising=False)
    monkeypatch.delenv("FB_DELAY_JITTER", raising=False)
    args = Namespace(max_posts=None, delay_base=None, delay_jitter=None)
    assert _resolve_tuning(args) == (50, 3.0, 2.0)
