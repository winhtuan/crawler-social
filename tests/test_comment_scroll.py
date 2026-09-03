import asyncio

from crawlfb.comments import (
    _click_exact_text,
    _click_view_more,
    _is_view_more_label,
    expand_comments,
    scroll_comment_list,
    switch_to_all_comments,
)
from crawlfb.config import Config


def _cfg() -> Config:
    return Config(page_url="https://www.facebook.com/p", output="out.json")


def test_view_more_label_matches_vi_en():
    assert _is_view_more_label("Xem thêm bình luận") is True
    assert _is_view_more_label("View more comments") is True
    assert _is_view_more_label("Xem thêm câu trả lời") is True
    assert _is_view_more_label("View more replies") is True
    assert _is_view_more_label("Hiển thị thêm phản hồi") is True


def test_view_more_label_rejects_composer_and_non_comment():
    assert _is_view_more_label("Viết bình luận...") is False
    assert _is_view_more_label("Write a comment...") is False
    assert _is_view_more_label("Viết nhận xét") is False
    assert _is_view_more_label("Thích") is False
    assert _is_view_more_label("") is False


def test_view_more_label_rejects_long_container():
    long = (
        "This is a long container description that happens to mention a comment "
        "somewhere in the middle but is far too long to be a tight button label"
    )
    assert _is_view_more_label(long) is False


class _EvalPage:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    async def evaluate(self, js, *args):
        self.calls.append((js, args))
        return self._results.pop(0)


def test_click_view_more_returns_int():
    page = _EvalPage([3])
    assert asyncio.run(_click_view_more(page)) == 3


def test_scroll_comment_list_returns_bool():
    page = _EvalPage([True])
    assert asyncio.run(scroll_comment_list(page)) is True


def test_click_exact_text_passes_text_arg():
    page = _EvalPage([True])
    assert asyncio.run(_click_exact_text(page, "Tất cả bình luận")) is True
    assert page.calls[0][1] == ("Tất cả bình luận",)


def test_switch_to_all_comments_opens_then_selects(monkeypatch):
    calls = []

    async def fake_click(page, text):
        calls.append(text)
        return text in ("Phù hợp nhất", "Tất cả bình luận")

    monkeypatch.setattr("crawlfb.comments._click_exact_text", fake_click)
    assert asyncio.run(switch_to_all_comments(None)) is True
    assert calls == ["Phù hợp nhất", "Tất cả bình luận"]


def test_switch_to_all_comments_no_trigger(monkeypatch):
    async def fake_click(page, text):
        return False

    monkeypatch.setattr("crawlfb.comments._click_exact_text", fake_click)
    assert asyncio.run(switch_to_all_comments(None)) is False


def test_switch_to_all_comments_english_labels(monkeypatch):
    calls = []

    async def fake_click(page, text):
        calls.append(text)
        return text in ("Most relevant", "All comments")

    monkeypatch.setattr("crawlfb.comments._click_exact_text", fake_click)
    assert asyncio.run(switch_to_all_comments(None)) is True
    # The trigger loop tries Vietnamese labels first, then English.
    assert calls == [
        "Phù hợp nhất", "Mới nhất", "Most relevant",
        "Tất cả bình luận", "All comments",
    ]


def test_expand_comments_counts_clicks(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        "crawlfb.comments.Humanizer", lambda **k: _FakeHuman()
    )
    monkeypatch.setattr("crawlfb.comments._click_view_more", _always(2))
    monkeypatch.setattr("crawlfb.comments.scroll_comment_list", _always_true())
    total = asyncio.run(expand_comments(None, _cfg(), rounds=3))
    assert total == 6


def test_expand_comments_stops_on_zero_streak(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        "crawlfb.comments.Humanizer", lambda **k: _FakeHuman()
    )
    monkeypatch.setattr("crawlfb.comments._click_view_more", _always(0))
    monkeypatch.setattr("crawlfb.comments.scroll_comment_list", _always_true())
    total = asyncio.run(expand_comments(None, _cfg(), rounds=10))
    assert total == 0


class _FakeHuman:
    async def pause(self):
        return None


def _always(n):
    async def _inner(page):
        return n

    return _inner


def _always_true():
    async def _inner(page):
        return True

    return _inner
