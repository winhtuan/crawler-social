from __future__ import annotations
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from dotenv import load_dotenv


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
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
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
    res_interval: float = 15.0
    proxy_rotate_minutes: float = 22.0
    proxy_from_env: bool = True

    def normalized_page_url(self) -> str:
        return self.page_url.rstrip("/") + "/"

    @classmethod
    def from_args(cls, args) -> "Config":
        load_dotenv()
        storage = args.storage_state or os.getenv("FB_STORAGE_STATE")
        return cls(
            page_url=args.page,
            output=args.output,
            max_posts=args.max_posts,
            headless=args.headless,
            proxy=Proxy.from_url(args.proxy or os.getenv("HTTP_PROXY")),
            delay_base=args.delay_base,
            delay_jitter=args.delay_jitter,
            storage_state=storage,
        )
