"""One-off: prove comments can be fetched by replaying the CommentList
query directly, without navigating to a permalink.

Run:  python tools/replay_comment_query.py <permalink> <control_id> <target_id> [out.json]

  1. Load <permalink> (the post whose id == control_id), switch to "All
     comments", and capture Facebook's CommentListComponentsRootQuery POST body.
  2. Replay that query via in-page fetch for:
       - control_id  -> should return comments (sanity: replay mechanism works)
       - target_id   -> a DIFFERENT post's comments (proof: no navigation needed)

If the target replay returns comments, the crawl can drop per-post page.goto()
and fetch comments straight from the feed-collected post ids.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

from crawlfb.comments import extract_comments, split_json_values, switch_to_all_comments
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context

COMMENT_QUERY_NAME = "CommentListComponentsRootQuery"


def _feedback_id(post_id: str) -> str:
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def _parse_form(body: str) -> dict:
    return dict(urllib.parse.parse_qsl(body))


async def _replay(page, body: dict, post_id: str) -> list[dict]:
    """POST a copy of `body` with `variables.id` rewritten to post_id, via the
    page's own fetch (so session cookies + origin are implicit). Returns the raw
    Comment nodes in the response, if any."""
    vars_ = json.loads(body["variables"])
    vars_["id"] = _feedback_id(post_id)
    new_body = urllib.parse.urlencode({**body, "variables": json.dumps(vars_)})
    raw = await page.evaluate(
        """async (body) => {
            const r = await fetch('/api/graphql/', {
                method: 'POST',
                headers: {'content-type': 'application/x-www-form-urlencoded'},
                body: body,
                credentials: 'include',
            });
            return await r.text();
        }""",
        new_body,
    )
    return extract_comments(split_json_values(raw))


def _mask(body: dict) -> dict:
    out = dict(body)
    for k in ("fb_dtsg", "lsd", "jazoest"):
        if k in out:
            out[k] = "<redacted>"
    return out


async def main(permalink: str, control_id: str, target_id: str, out: str) -> None:
    load_dotenv()
    cfg = Config(
        page_url=permalink,
        output="x.json",
        max_posts=1,
        headless=True,
        proxy=Proxy.from_url(os.getenv("HTTP_PROXY")),
        storage_state=os.getenv("FB_STORAGE_STATE", ".storage_state.json"),
    )
    captured: list[str] = []

    async with launch_context(cfg) as (_ctx, page):
        async def on_request(req) -> None:
            if "/api/graphql/" in req.url and req.method == "POST":
                try:
                    b = req.post_data
                except Exception:
                    return
                if COMMENT_QUERY_NAME in b:
                    captured.append(b)

        page.on("request", on_request)
        await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
        await switch_to_all_comments(page)

        # Wait for the "All comments" CommentList query to fire.
        for _ in range(20):
            if captured:
                break
            await asyncio.sleep(0.5)
        if not captured:
            print("FAIL: no CommentListComponentsRootQuery captured")
            return

        body = _parse_form(captured[-1])
        control_comments = await _replay(page, body, control_id)
        target_comments = await _replay(page, body, target_id)

    result = {
        "permalink": permalink,
        "control_id": control_id,
        "target_id": target_id,
        "captured_query": _mask(body),
        "control_comments": len(control_comments),
        "target_comments": len(target_comments),
        "target_sample": [c.get("text", "")[:80] for c in target_comments[:3]],
    }
    Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"control ({control_id}): {len(control_comments)} comments")
    print(f"target  ({target_id}): {len(target_comments)} comments")
    print(f"sample: {result['target_sample']}")
    print(f"-> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    permalink = sys.argv[1]
    control_id = sys.argv[2]
    target_id = sys.argv[3]
    out = sys.argv[4] if len(sys.argv) > 4 else "replay_result.json"
    asyncio.run(main(permalink, control_id, target_id, out))
