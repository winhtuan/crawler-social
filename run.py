"""Orchestrate one crawl run: rotate proxy -> crawl -> upload (even on Ctrl+C).

The crawl itself (crawlfb.cli) now also fetches the ~3 most recent posts from
an external API (scrapecreators -> apify) and crawls their comments. The S3
upload always runs, so partial output files still land on S3 when the crawl is
interrupted mid-way. Replaces the 3-command chain in crawl.bat.

Run:  python run.py --max-posts 10
"""
from __future__ import annotations

import subprocess
import sys


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=False)


def main() -> None:
    python = sys.executable
    _run([python, "tools/rotate_proxy.py"])
    crawl = [python, "-m", "crawlfb.cli", *sys.argv[1:]]
    try:
        _run(crawl)
    except KeyboardInterrupt:
        pass
    finally:
        print("\nuploading output to S3...")
        _run([python, "tools/upload_s3.py"])


if __name__ == "__main__":
    main()
