"""Orchestrate one crawl run: rotate proxy -> crawl -> upload (even on Ctrl+C).

The crawl itself (crawlfb.cli) now also fetches the ~3 most recent posts from
an external API (scrapecreators -> apify) and crawls their comments. The S3
upload runs after the crawl, so partial output files still land on S3 when the
crawl is interrupted mid-way. Replaces the 3-command chain in crawl.bat.

Run:  python run.py --max-posts 10
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False)


def main() -> None:
    python = sys.executable
    _run([python, "tools/rotate_proxy.py"])

    output_dir = Path(__file__).resolve().parent / "output"
    before = set(output_dir.glob("*.json"))

    crawl = [python, "-m", "crawlfb.cli", *sys.argv[1:]]
    try:
        _run(crawl)
    except KeyboardInterrupt:
        pass

    # Upload only the files this run produced. If the crawl was interrupted
    # before it wrote anything (no posts collected), there are no new files and
    # we must NOT fall back to a stale file from an earlier run. The feed
    # checkpoint (*.feed.json) is a local resume artifact, not a crawl result.
    new_files = sorted(
        f for f in set(output_dir.glob("*.json")) - before
        if not f.name.endswith(".feed.json")
    )
    print("\nuploading output to S3...")
    if not new_files:
        print("no new output files — skipping upload")
        return
    for f in new_files:
        _run([python, "tools/upload_s3.py", "--file", str(f)])


if __name__ == "__main__":
    main()
