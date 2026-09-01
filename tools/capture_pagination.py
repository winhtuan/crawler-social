"""One-off: load a high-comment post and capture the comment-pagination
GraphQL query (the follow-up request that fetches the NEXT page of comments).

Run:  python tools/capture_pagination.py <permalink> [out.json]

The initial CommentListComponentsRootQuery only returns the first page. Older
comments arrive via a second doc_id whose variables carry a cursor. This tool
scrolls the comment-list container until those pagination requests fire, then
summarizes every captured /api/graphql/ POST by doc_id + friendly name.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

from crawlfb.comments import scroll_comment_list, switch_to_all_comments
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context

_SECRET_KEYS = ("fb_dtsg", "lsd", "jazoest", "__spin_r", "__s", "__hsi")


def _summarize(body: str) -> dict:
    obj = dict(urllib.parse.parse_qsl(body))
    try:
        vars_ = json.loads(obj.get("variables") or "{}")
    except Exception:
        vars_ = {}
    masked = {k: (v if k not in _SECRET_KEYS else "<redacted>") for k, v in obj.items()}
    masked["variables"] = vars_
    return masked


async def main(permalink: str, out: str) -> None:
    load_dotenv()
    cfg = Config(
        page_url=permalink,
        output="x.json",
        max_posts=1,
        headless=True,
        proxy=Proxy.from_url(os.getenv("HTTP_PROXY")),
        storage_state=os.getenv("FB_STORAGE_STATE", ".storage_state.json"),
    )
    requests: list[str] = []

    async with launch_context(cfg) as (_ctx, page):
        async def on_request(req) -> None:
            if "/api/graphql/" in req.url and req.method == "POST":
                try:
                    b = req.post_data
                except Exception:
                    return
                requests.append(b)

        page.on("request", on_request)
        await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
        await switch_to_all_comments(page)
        await asyncio.sleep(1.0)

        # Scroll the comment-list container many rounds so the "load older
        # comments" pagination requests fire.
        for _ in range(40):
            await scroll_comment_list(page)
            await asyncio.sleep(0.6)

    summary = [_summarize(b) for b in requests]
    Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    seen = {}
    for s in summary:
        key = (s.get("doc_id"), s.get("fb_api_req_friendly_name"))
        seen.setdefault(key, 0)
        seen[key] += 1
    print(f"captured {len(summary)} graphql POSTs -> {out}")
    for (doc, name), n in seen.items():
        print(f"  doc_id={doc}  name={name}  x{n}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    permalink = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "pagination.json"
    asyncio.run(main(permalink, out))
