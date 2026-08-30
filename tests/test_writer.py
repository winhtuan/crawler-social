from pathlib import Path
from crawlfb.models import Post
from crawlfb.writer import write_posts

def _post(pid: str) -> Post:
    return Post(postId=pid, pageName="p", text="hi")

def test_write_posts_creates_array_and_dedupes(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), _post("2")], out) == 2
    assert write_posts([_post("2"), _post("3")], out) == 1  # "2" đã có
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert [p["postId"] for p in data] == ["1", "2", "3"]

def test_write_posts_skips_posts_without_id(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), Post()], out) == 1
