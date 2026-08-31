"""Rotate the KiotProxy and write the new HTTP_PROXY into .env.

Reads PROXY_KEY_VALUE (and optional PROXY_REGION) from .env, asks KiotProxy for
the current proxy, and rotates to a fresh one when the cooldown (ttc) is over.
Rewrites the HTTP_PROXY= line in .env so the next crawl uses the new IP.

Run:  python tools/rotate_proxy.py
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

BASE = "https://api.kiotproxy.com/api/v1/proxies"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _as_http_proxy(data: dict) -> str:
    """Map a KiotProxy data object to the http proxy URL (adds http:// scheme)."""
    http = (data or {}).get("http") or ""
    if http and "://" not in http:
        http = "http://" + http
    return http


def rewrite_env(text: str, http_proxy: str) -> str:
    """Replace (or append) the HTTP_PROXY= line in .env text."""
    lines = text.splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("HTTP_PROXY="):
            out.append(f"HTTP_PROXY={http_proxy}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"HTTP_PROXY={http_proxy}")
    return "\n".join(out) + "\n"


def main() -> int:
    load_dotenv()
    key = (os.getenv("PROXY_KEY_VALUE") or "").strip()
    if not key:
        print("PROXY_KEY_VALUE empty in .env")
        return 1
    region = (os.getenv("PROXY_REGION") or "random").strip()

    data: dict = {}
    ttc = 0
    # Current proxy + cooldown. First use has no current proxy -> rotate below.
    try:
        cur = _get(f"{BASE}/current?key={urllib.parse.quote(key)}")
        if cur.get("success"):
            data = cur.get("data") or {}
            ttc = data.get("ttc") or 0
    except Exception as exc:
        print(f"current failed: {exc}")

    if ttc == 0:
        try:
            new = _get(f"{BASE}/new?key={urllib.parse.quote(key)}&region={region}")
            if new.get("success"):
                data = new.get("data") or {}
        except Exception as exc:
            print(f"new failed: {exc}")

    http_proxy = _as_http_proxy(data)
    if not http_proxy:
        print("no http proxy returned")
        return 1

    env_path = Path(__file__).resolve().parent.parent / ".env"
    env_path.write_text(
        rewrite_env(env_path.read_text(encoding="utf-8"), http_proxy),
        encoding="utf-8",
    )
    print(f"[OK] proxy updated -> HTTP_PROXY={http_proxy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
