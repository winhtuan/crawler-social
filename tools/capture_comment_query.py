"""One-off: open a post permalink, dump the comment GraphQL request payload
(doc_id + variables + fb_dtsg) and the fb_dtsg embedded in the page HTML.

Purpose: the crawl currently scrapes comments by navigating to each permalink
and letting Facebook's own JS fire /api/graphql/ comment pagination. To replay
that query directly (no permalink render + no scroll), we need the exact
request body. This tool captures it so the payload shape can be inspected.

Run:  python tools/capture_comment_query.py <permalink_url> [out.json]
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from crawlfb.comments import expand_comments, switch_to_all_comments
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context

# fb_dtsg lives in the page's DTSGInitialData blob (window._jsd), not in a
# cookie. FB changes the exact wrapper over time, so try the known shapes and
# also dump the raw _jsd so the current structure can be read by eye.
_FB_DTSG_RES = [
    re.compile(r'"DTSGInitialData"\s*,\s*\[\]\s*,\s*\{\s*"token"\s*:\s*"([^"]+)"'),
    re.compile(r'"fb_dtsg"\s*:\s*"([^"]+)"'),
    re.compile(r'name="fb_dtsg"\s+value="([^"]+)"'),
]


def extract_fb_dtsg(html: str) -> str:
    for rx in _FB_DTSG_RES:
        m = rx.search(html)
        if m:
            return m.group(1)
    return ""


async def _jsd(page) -> dict | None:
    """The raw DTSG initial-data object, if FB still exposes it on window."""
    try:
        return await page.evaluate("() => window._jsd")
    except Exception:
        return None


async def main(permalink: str, out: str) -> None:
    load_dotenv()
    cfg = Config(
        page_url=permalink,
        output="x.json",
        max_posts=1,
        headless=False,
        proxy=Proxy.from_url(os.getenv("HTTP_PROXY")),
        storage_state=os.getenv("FB_STORAGE_STATE", ".storage_state.json"),
    )
    requests: list[dict] = []

    async def on_request(req) -> None:
        if "/api/graphql/" not in req.url or req.method != "POST":
            return
        try:
            body = req.post_data
        except Exception:
            body = None
        if body is None:
            return
        # Keep only the pieces needed to replay: the query id (doc_id) and its
        # variables. The fb_dtsg is a separate top-level field in the body.
        requests.append({"url": req.url, "post_data": body})

    async with launch_context(cfg) as (_ctx, page):
        page.on("request", on_request)
        await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2.0)

        html = await page.content()
        fb_dtsg = extract_fb_dtsg(html)
        jsd = await _jsd(page)

        # Trigger the same comment-pagination path the crawl uses, so the
        # interceptor sees the comment query (not just the timeline feed query).
        await switch_to_all_comments(page)
        await asyncio.sleep(1.0)
        await expand_comments(page, cfg, rounds=4)

    result = {
        "permalink": permalink,
        "fb_dtsg_from_html": fb_dtsg,
        "window_jsd": jsd,
        "graphql_requests": requests,
    }
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"fb_dtsg: {fb_dtsg or '(not found in html)'}")
    print(f"captured {len(requests)} graphql POST bodies -> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    permalink = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "comment_query.json"
    asyncio.run(main(permalink, out))
