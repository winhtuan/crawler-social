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
