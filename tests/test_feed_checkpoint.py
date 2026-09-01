import json
from pathlib import Path
from crawlfb.feed_checkpoint import (
    PENDING, DONE, checkpoint_path, build_records, save, load,
)


def test_checkpoint_path_replaces_json_suffix():
    out = Path("output") / "lopnguoita.fp_20260901_200216.json"
    assert checkpoint_path(out) == Path("output") / "lopnguoita.fp_20260901_200216.feed.json"


def test_build_records_adds_pending_status():
    records = build_records([{"post_id": "1", "permalink_url": "https://x/1"}])
    assert records == [{"post_id": "1", "permalink_url": "https://x/1", "crawl_status": PENDING}]


def test_save_load_roundtrip(tmp_path):
    path = tmp_path / "run.feed.json"
    records = build_records([
        {"post_id": "1", "permalink_url": "https://x/1"},
        {"post_id": "2", "permalink_url": "https://x/2"},
    ])
    save(records, path)
    assert load(path) == records


def test_load_missing_returns_empty(tmp_path):
    assert load(tmp_path / "nope.feed.json") == []


def test_load_corrupt_returns_empty(tmp_path):
    path = tmp_path / "run.feed.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load(path) == []


def test_status_update_persists(tmp_path):
    path = tmp_path / "run.feed.json"
    records = build_records([{"post_id": "1"}])
    save(records, path)
    records[0]["crawl_status"] = DONE
    save(records, path)
    assert load(path)[0]["crawl_status"] == DONE
