"""Open a visible browser, log into Facebook by hand, then save the session.

Run:  HTTP_PROXY= python tools/login.py

The browser opens at facebook.com. Log in (password + 2FA as usual). When the
home feed shows your account, press Enter here. The script then writes the
authenticated session (c_user + xs cookies) to .storage_state.json so the
crawler is no longer treated as logged-out.

Why: the crawler was silently running logged-out — .storage_state.json held
only tracking cookies (no c_user / xs), so Facebook gated the feed to ~2
posts behind a login wall. A fresh login fixes it.
"""
import asyncio
import os
from dotenv import load_dotenv
from crawlfb.config import Config, Proxy
from crawlfb.stealth import launch_context


async def _login() -> None:
    load_dotenv()
    storage = os.getenv("FB_STORAGE_STATE", ".storage_state.json")
    cfg = Config(
        page_url="https://www.facebook.com/",
        output="x.json",
        max_posts=1,
        headless=False,          # visible browser so you can log in
        humanize=False,          # no auto mouse/scroll while you type
        proxy=Proxy.from_url(os.getenv("HTTP_PROXY")),
        storage_state=storage,
    )
    async with launch_context(cfg) as (_ctx, page):
        await page.goto("https://www.facebook.com/", wait_until="domcontentloaded",
                        timeout=60000)
        print("\nLog into Facebook in the browser window (password + 2FA).")
        print("When your home feed is showing, come back here and press Enter.")
        await asyncio.to_thread(input, "")
        # launch_context saves context.storage_state() to cfg.storage_state on
        # exit, so the fresh cookies land in .storage_state.json automatically.
    print(f"session saved -> {storage}")


if __name__ == "__main__":
    asyncio.run(_login())
