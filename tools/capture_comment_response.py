"""One-off: capture the RESPONSE of the comment root + pagination queries to
locate the "next page" cursor field.

Run:  python tools/capture_comment_response.py <permalink> [out.json]

Saves each response body (decoded graphql values) keyed by query name, so the
cursor path (the value later echoed as `commentsAfterCursor`) can be read off
the structure instead of guessed.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

from crawlfb.comments import scroll_comment_list, split_json_values, switch_to_all_comments
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context

_DOC_NAMES = {
    "27046361795040764": "CommentListComponentsRootQuery",
    "27973447728944010": "CommentsListComponentsPaginationQuery",
}


def _query_name(resp) -> str | None:
    try:
        req = resp.request
        if req.method != "POST":
            return None
        body = req.post_data or ""
    except Exception:
        return None
    for doc_id, name in _DOC_NAMES.items():
        if doc_id in body:
            return name
    return None


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
    responses: dict[str, list] = {}

    async with launch_context(cfg) as (_ctx, page):
        async def on_response(resp) -> None:
            name = _query_name(resp)
            if name is None:
                return
            try:
                text = await resp.text()
            except Exception:
                return
            responses.setdefault(name, []).append(split_json_values(text))

        page.on("response", on_response)
        await page.goto(permalink, wait_until="domcontentloaded", timeout=60000)
        await switch_to_all_comments(page)
        await asyncio.sleep(1.0)
        # A few scrolls fire the root + first pagination pages.
        for _ in range(6):
            await scroll_comment_list(page)
            await asyncio.sleep(0.6)

    Path(out).write_text(json.dumps(responses, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, pages in responses.items():
        print(f"{name}: {len(pages)} response(s)")
    print(f"-> {out}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    permalink = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "comment_response.json"
    asyncio.run(main(permalink, out))
