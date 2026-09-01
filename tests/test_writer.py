import json
from pathlib import Path
from crawlfb.models import Post
from crawlfb.writer import write_posts, checkpoint_posts

def _post(pid: str) -> Post:
    return Post(post_id=pid, page_name="p", text="hi")

def test_write_posts_creates_array_and_dedupes(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), _post("2")], out) == 2
    assert write_posts([_post("2"), _post("3")], out) == 1  # "2" đã có
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["post_id"] for p in data] == ["1", "2", "3"]

def test_write_posts_skips_posts_without_id(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), Post()], out) == 1

def _raw(pid: str) -> dict:
    return {"post_id": pid, "permalink_url": f"https://fb.com/{pid}", "text": "hi"}


def test_checkpoint_posts_writes_empty_comment_records(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([_raw("1"), _raw("2")], "p", out)
    assert written == {"1", "2"}
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["post_id"] for p in data] == ["1", "2"]
    assert all(p["comments_list"] == [] for p in data)


def test_checkpoint_posts_skips_already_written_ids(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([_raw("1")], "p", out)
    written = checkpoint_posts([_raw("1"), _raw("2")], "p", out, written_ids=written)
    assert written == {"1", "2"}
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["post_id"] for p in data] == ["1", "2"]


def test_checkpoint_posts_skips_posts_without_id(tmp_path: Path):
    out = tmp_path / "out.json"
    written = checkpoint_posts([{"text": "no id"}], "p", out)
    assert written == set()
    assert not out.exists()
