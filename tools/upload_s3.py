"""Upload crawled JSON files to S3.

Key layout:  {dd-MM-yyyy}/{page_id}/{page_id}_{run_id}.json
  - dd-MM-yyyy  = the run's crawl date (from run_id YYYYMMDD_HHMMSS)
  - page_id     = the page id (filename prefix)
  - run_id      = YYYYMMDD_HHMMSS

By default uploads every file from the latest run (max run_id in output/).
Use --file to upload one specific file, --dry-run to print keys only.

Reads AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME, AWS_REGION
from .env.

Run:  python tools/upload_s3.py
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from pathlib import Path

import boto3
from dotenv import load_dotenv

_FILENAME_RE = re.compile(r"^(?P<id>.+)_(?P<run>\d{8}_\d{6})\.json$")


def parse_filename(name: str) -> tuple[str, str] | None:
    """(page_id, run_id) from a filename like 'cotsongGenZ.YAN_20260831_202232.json'."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    return m.group("id"), m.group("run")


def s3_key(page_id: str, run_id: str) -> str:
    """Build the S3 key for one file from its page id and run id."""
    dt = datetime.strptime(run_id.split("_")[0], "%Y%m%d")
    date = dt.strftime("%d-%m-%Y")
    return f"{date}/{page_id}/{page_id}_{run_id}.json"


def _latest_run_files(output_dir: Path) -> list[Path]:
    """Files belonging to the newest run_id in output_dir."""
    files = [p for p in output_dir.glob("*.json")]
    runs: dict[str, list[Path]] = {}
    for p in files:
        parsed = parse_filename(p.name)
        if parsed:
            _, run_id = parsed
            runs.setdefault(run_id, []).append(p)
    if not runs:
        return []
    latest = max(runs)
    return runs[latest]


def _client():
    return boto3.client(
        "s3",
        region_name=os.getenv("AWS_REGION", "ap-southeast-1"),
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


def main() -> int:
    load_dotenv()
    bucket = (os.getenv("S3_BUCKET_NAME") or "").strip()
    if not bucket:
        print("S3_BUCKET_NAME empty in .env")
        return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="upload one specific file")
    parser.add_argument("--dry-run", action="store_true", help="print keys only")
    args = parser.parse_args()

    output_dir = Path(__file__).resolve().parent.parent / "output"
    if args.file:
        files = [Path(args.file)]
    else:
        files = _latest_run_files(output_dir)

    if not files:
        print("no json files to upload")
        return 1

    s3 = _client()
    for path in files:
        parsed = parse_filename(path.name)
        if not parsed:
            print(f"skip {path.name} (unrecognized name)")
            continue
        page_id, run_id = parsed
        key = s3_key(page_id, run_id)
        if args.dry_run:
            print(f"[dry-run] {path} -> s3://{bucket}/{key}")
            continue
        s3.upload_file(str(path), bucket, key)
        print(f"[OK] {path.name} -> s3://{bucket}/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
