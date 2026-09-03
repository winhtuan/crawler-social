from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class Proxy:
    server: str
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_url(cls, url: str | None) -> "Proxy | None":
        if not url:
            return None
        parsed = urlparse(url)
        if not parsed.hostname:
            return None
        port = f":{parsed.port}" if parsed.port else ""
        server = f"{parsed.scheme}://{parsed.hostname}{port}"
        return cls(
            server=server,
            username=parsed.username,
            password=parsed.password,
        )

    def to_playwright(self) -> dict:
        d = {"server": self.server}
        if self.username:
            d["username"] = self.username
        if self.password:
            d["password"] = self.password
        return d


@dataclass
class Config:
    page_url: str
    output: str
    max_posts: int = 50
    max_comments: int = 0  # 0 = no cap (scrape all)
    headless: bool = True
    humanize: bool = True
    proxy: Proxy | None = None
    delay_base: float = 3.0
    delay_jitter: float = 2.0
    storage_state: str | None = None
    scroll_distance: int = 2000
    stall_limit: int = 5
    proxy_rotate_minutes: float = 22.0
    proxy_from_env: bool = True

    def normalized_page_url(self) -> str:
        return self.page_url.rstrip("/") + "/"
