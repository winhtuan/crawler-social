from __future__ import annotations
import json
from contextlib import asynccontextmanager
from typing import AsyncIterator
from playwright.async_api import async_playwright, BrowserContext, Page
from crawlfb.config import Config

# UA Chrome-on-Windows ổn định gần đây. Giữ là hằng module để test.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Chạy trước mọi script của trang; ẩn các dấu hiệu automation mà FB fingerprint.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['vi-VN', 'vi', 'en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = {runtime: {}};
"""


_SAMESITE_MAP = {
    "no_restriction": "None",
    "lax": "Lax",
    "strict": "Strict",
}


def _convert_cookie_editor(cookies: list) -> dict:
    """Cookie-Editor / EditThisCookie export -> Playwright storage_state.

    Chrome cookie fields (sameSite: no_restriction|lax|strict, expirationDate,
    session) don't match Playwright's shape (sameSite: Strict|Lax|None,
    expires). Map each cookie, drop foreign keys, skip entries missing
    name/value."""
    converted = []
    for c in cookies:
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        same_site = c.get("sameSite")
        converted.append({
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain", ""),
            "path": c.get("path", "/"),
            "expires": -1 if c.get("session") else c.get("expirationDate", -1),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure": bool(c.get("secure", False)),
            "sameSite": _SAMESITE_MAP.get(same_site, "Lax"),
        })
    return {"cookies": converted}


def _load_storage_state(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if isinstance(raw, dict):
        return raw
    # Cookie-Editor / EditThisCookie export is a bare array of cookie objects;
    # convert it into Playwright's {cookies: [...]} storage_state shape.
    if isinstance(raw, list):
        return _convert_cookie_editor(raw)
    return None


@asynccontextmanager
async def launch_context(cfg: Config) -> AsyncIterator[tuple[BrowserContext, Page]]:
    storage_state = _load_storage_state(cfg.storage_state)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=cfg.headless)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=USER_AGENT,
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh",
            proxy=cfg.proxy.to_playwright() if cfg.proxy else None,
            storage_state=storage_state,
        )
        await context.add_init_script(STEALTH_JS)
        page = await context.new_page()
        try:
            yield context, page
        finally:
            if cfg.storage_state and storage_state is not None:
                try:
                    state = await context.storage_state()
                    with open(cfg.storage_state, "w", encoding="utf-8") as f:
                        json.dump(state, f)
                except (OSError, IOError):
                    pass
            await context.close()
            await browser.close()
