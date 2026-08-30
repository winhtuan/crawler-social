"""One-off: load a public page, dump every /api/graphql/ response to a file."""
import asyncio
import json
import sys
from pathlib import Path
from crawlfb.config import Config
from crawlfb.stealth import launch_context


def split_json_values(text: str) -> list:
    """Facebook graphql batch responses concatenate several JSON values with no
    wrapping array, so resp.json() fails on them ("Extra data"). Split manually."""
    dec = json.JSONDecoder()
    out = []
    i = 0
    n = len(text)
    while i < n:
        while i < n and text[i] in " \r\n\t":
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(text, i)
            out.append(obj)
        except json.JSONDecodeError:
            i += 1
    return out


async def main(page_url: str, out: str) -> None:
    cfg = Config(page_url=page_url, output=out, max_posts=5)
    captured = []
    async with launch_context(cfg) as (_ctx, page):
        async def on_response(resp):
            if "/api/graphql/" in resp.url and resp.status == 200:
                try:
                    text = await resp.text()
                    captured.append({"url": resp.url, "body": split_json_values(text)})
                except Exception:
                    pass
        page.on("response", on_response)
        await page.goto(cfg.normalized_page_url(), wait_until="networkidle", timeout=60000)
        # Logged-out FB does not emit /api/graphql/ on passive load - the feed is
        # inlined in the HTML. Opening the reaction-count flyout / a post fires
        # the Comet ProfileCometTimelineFeed graphql batches that carry the stories.
        for _ in range(2):
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            await asyncio.sleep(0.5)
        for label in ("Tất cả cảm xúc", "Bình luận"):
            try:
                el = page.get_by_text(label, exact=False).first
                if await el.count():
                    await el.click(timeout=4000, force=True)
                    await asyncio.sleep(6)
                    break
            except Exception:
                pass
        try:
            await page.locator('[role="article"]').first.click(timeout=4000, force=True)
            await asyncio.sleep(6)
        except Exception:
            pass
        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await asyncio.sleep(2)
        await asyncio.sleep(8)  # let the feed settle
    Path(out).write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"captured {len(captured)} responses -> {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
