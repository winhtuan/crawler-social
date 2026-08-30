# Kế hoạch triển khai Facebook Page Crawler

> **Cho worker agentic:** SUB-SKILL BẮT BUỘC: Dùng superpowers:subagent-driven-development (khuyến nghị) hoặc superpowers:executing-plans để triển khai plan này theo từng task. Các bước dùng cú pháp checkbox (`- [ ]`) để theo dõi tiến độ.

**Mục tiêu:** Một tool CLI bằng Python quét các bài post từ trang Facebook công khai bằng Playwright (chế độ stealth), ghi ra file JSON đúng shape của Apify "Facebook Posts Scraper", hỗ trợ proxy + delay giả lập người dùng để tránh bị nhận diện là bot, và có điểm mở rộng sạch để sau này crawl comment theo từng post.

**Kiến trúc:** Playwright điều khiển Chromium thật với fingerprint stealth (UA giả, patch `navigator.webdriver`, locale/timezone vi-VN). Tool load trang timeline công khai, chặn (intercept) response `/api/graphql/` ngay trong browser (đúng loại dữ liệu có cấu trúc mà Apify dùng), flatten từng story thành dict `RawStory` ổn định, normalize thành model pydantic `Post`, rồi ghi các bản ghi đã dedupe ra JSON. Các trường deterministic (`feedbackId`, `topLevelUrl`) được tính toán thay vì scrape. `Humanizer` chèn các khoảng pause ngẫu nhiên và cuộn trang giống người thật giữa các request.

**Tech Stack:** Python 3.13, Playwright (Chromium), pydantic v2, python-dotenv, argparse (stdlib). Không cần login — chỉ trang công khai.

**Spec:** Tham chiếu hành vi là Apify actor `zanTWNqB3Poz44qdY` (Facebook Posts Scraper). Hợp đồng output bắt buộc là `crawl-fb/CotSongGenZ_Page.json` — mọi field trong file đó phải được tái tạo chính xác, và bất kỳ post mới nào cũng phải serialize ra đúng schema đó.

## Ràng buộc toàn cục

- Output là một mảng JSON các object post; key của mỗi object đúng bằng tập key trong `crawl-fb/CotSongGenZ_Page.json` (không thừa key top-level, không thiếu key).
- `feedbackId` luôn là `base64("feedback:" + postId)` — được tính, không scrape.
- `topLevelUrl` luôn là `https://www.facebook.com/{pageId}/posts/{postId}` — được tính.
- `likes` = tổng tất cả reaction theo loại; `topReactionsCount` = số loại reaction có giá trị khác 0.
- `inputUrl` và `facebookUrl` là URL trang người dùng truyền vào, chuẩn hóa thêm dấu `/` ở cuối.
- Chỉ trang công khai. Không bao giờ gửi `FB-ACCESS-TOKEN` (đã có trong `crawl-fb/.env`) trong bất kỳ request nào ở v1 — token dành cho task enrich Graph-API trong tương lai, không dùng ở đây.
- Mọi secret (credential proxy, đường dẫn storage-state) đọc từ `.env`, không hardcode, không commit.
- Python version floor 3.13 (chuẩn repo). Dependencies pin trong `requirements.txt`.

---

### Task 1: Scaffolding project, models, và config

**Files:**
- Tạo: `crawl-fb/requirements.txt`
- Tạo: `crawl-fb/.gitignore`
- Tạo: `crawl-fb/.env.example`
- Tạo: `crawl-fb/src/crawlfb/__init__.py`
- Tạo: `crawl-fb/src/crawlfb/models.py`
- Tạo: `crawl-fb/src/crawlfb/config.py`
- Tạo: `crawl-fb/src/crawlfb/__main__.py` (stub, in "not implemented")
- Test: `crawl-fb/tests/test_models.py`
- Test: `crawl-fb/tests/test_config.py`

**Interfaces:**
- Sinh ra: `crawlfb.models.Post`, `User`, `Media`, `PhotoImage`, `MediaFeedback` — model pydantic được `normalize.py` (Task 4) và `writer.py` (Task 6) dùng.
- Sinh ra: `crawlfb.config.Config`, `Proxy` — dataclass được `stealth.py` (Task 2) và `paginate.py` (Task 5) dùng.

- [ ] **Bước 1: Viết test fail trước**

`crawl-fb/tests/test_models.py`:
```python
import json
from pathlib import Path
from crawlfb.models import Post

REF = json.loads(
    (Path(__file__).parent.parent / "CotSongGenZ_Page.json").read_text(encoding="utf-8")
)[0]

def test_post_parses_reference_json():
    post = Post.model_validate(REF)
    assert post.postId == "1360424439627222"
    assert post.pageName == "CotSongGenZ.Page"
    assert post.text.startswith("Tỏ tình xong hắc")
    assert post.likes == 137
    assert post.reactionHahaCount == 69
    assert post.reactionLikeCount == 58
    assert post.reactionSadCount == 9
    assert post.reactionLoveCount == 1
    assert post.topReactionsCount == 4
    assert post.comments == 1
    assert post.shares == 1
    assert post.paidPartnership is False
    assert post.user.id == "100069790373758"
    assert post.user.name == "Cột Sống Gen Z"

def test_post_roundtrip_preserves_top_level_keys():
    post = Post.model_validate(REF)
    dumped = post.model_dump()
    assert set(dumped.keys()) == set(REF.keys())

def test_media_parses_reference_json():
    post = Post.model_validate(REF)
    assert len(post.media) == 1
    m = post.media[0]
    assert m.__typename == "Photo"
    assert m.__isMedia == "Photo"
    assert m.photo_image.uri.startswith("https://scontent")
    assert m.photo_image.height == 526
    assert m.photo_image.width == 526
    assert "May be an image of text" in m.ocrText
```

`crawl-fb/tests/test_config.py`:
```python
from crawlfb.config import Proxy, Config

def test_proxy_parse_plain():
    p = Proxy.from_url("http://127.0.0.1:8080")
    assert p.server == "http://127.0.0.1:8080"
    assert p.username is None and p.password is None

def test_proxy_parse_with_auth():
    p = Proxy.from_url("http://user:pass@127.0.0.1:8080")
    assert p.username == "user" and p.password == "pass"
    assert p.server == "http://127.0.0.1:8080"

def test_config_normalizes_page_url():
    cfg = Config(page_url="https://www.facebook.com/CotSongGenZ.Page", output="out.json")
    assert cfg.normalized_page_url() == "https://www.facebook.com/CotSongGenZ.Page/"
```

- [ ] **Bước 2: Chạy test để xác nhận fail**

Chạy: `cd crawl-fb && python -m pytest tests/test_models.py tests/test_config.py -v`
Kỳ vọng: FAIL — `ModuleNotFoundError: No module named 'crawlfb'` (hoặc ImportError cho các class).

- [ ] **Bước 3: Viết scaffolding + models + config**

`crawl-fb/requirements.txt`:
```
playwright==1.49.1
pydantic==2.10.4
python-dotenv==1.0.1
```

`crawl-fb/.gitignore`:
```
.env
__pycache__/
*.pyc
output/
.storage_state.json
.venv/
```

`crawl-fb/.env.example`:
```
# Proxy SOCKS5/HTTP tùy chọn (để trống để chạy không proxy)
FB_PROXY=
# Lưu cookie/session để FB thấy visitor quay lại
FB_STORAGE_STATE=.storage_state.json
```

`crawl-fb/src/crawlfb/__init__.py`:
```python
__version__ = "0.1.0"
```

`crawl-fb/src/crawlfb/models.py`:
```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    name: str
    profileUrl: str
    profilePic: str


class PhotoImage(BaseModel):
    uri: str
    height: Optional[int] = None
    width: Optional[int] = None


class MediaFeedback(BaseModel):
    can_viewer_comment: bool = False
    id: Optional[str] = None


class Media(BaseModel):
    thumbnail: Optional[str] = None
    __typename: Optional[str] = None
    __isMedia: Optional[str] = None
    accent_color: Optional[str] = None
    photo_product_tags: list = Field(default_factory=list)
    photo_image: Optional[PhotoImage] = None
    url: Optional[str] = None
    id: Optional[str] = None
    feedback: Optional[MediaFeedback] = None
    ocrText: Optional[str] = None


class Post(BaseModel):
    facebookUrl: Optional[str] = None
    postId: Optional[str] = None
    pageName: Optional[str] = None
    url: Optional[str] = None
    time: Optional[str] = None
    timestamp: Optional[int] = None
    user: Optional[User] = None
    text: Optional[str] = None
    likes: int = 0
    comments: int = 0
    shares: int = 0
    topReactionsCount: int = 0
    media: list[Media] = Field(default_factory=list)
    feedbackId: Optional[str] = None
    reactionHahaCount: int = 0
    reactionLikeCount: int = 0
    reactionSadCount: int = 0
    reactionLoveCount: int = 0
    paidPartnership: bool = False
    topLevelUrl: Optional[str] = None
    facebookId: Optional[str] = None
    inputUrl: Optional[str] = None
```

`crawl-fb/src/crawlfb/config.py`:
```python
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
    headless: bool = True
    proxy: Proxy | None = None
    delay_base: float = 3.0
    delay_jitter: float = 2.0
    storage_state: str | None = None
    scroll_distance: int = 2000
    stall_limit: int = 5

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
            proxy=Proxy.from_url(args.proxy or os.getenv("FB_PROXY")),
            delay_base=args.delay_base,
            delay_jitter=args.delay_jitter,
            storage_state=storage,
        )
```

`crawl-fb/src/crawlfb/__main__.py`:
```python
def main() -> None:
    raise SystemExit("not implemented yet — run after Task 7")


if __name__ == "__main__":
    main()
```

- [ ] **Bước 4: Chạy test để xác nhận pass**

Chạy: `cd crawl-fb && python -m pytest tests/ -v`
Kỳ vọng: PASS (5 tests).

- [ ] **Bước 5: Commit**

```bash
git add crawl-fb/requirements.txt crawl-fb/.gitignore crawl-fb/.env.example crawl-fb/src/crawlfb/ crawl-fb/tests/
git commit -m "feat(crawl-fb): scaffold project with Post models and Config"
```

---

### Task 2: Stealth browser launch + proxy + session persistence

**Files:**
- Tạo: `crawl-fb/src/crawlfb/stealth.py`
- Test: `crawl-fb/tests/test_stealth.py`

**Interfaces:**
- Dùng: `crawlfb.config.Config`, `Proxy.to_playwright()` (Task 1).
- Sinh ra: `async launch_context(cfg: Config) -> AsyncIterator[tuple[BrowserContext, Page]]` — async context manager trả về `(context, page)`. Được `cli.py` (Task 7) và script capture (Task 3) dùng.

- [ ] **Bước 1: Viết test fail trước**

`crawl-fb/tests/test_stealth.py` (chỉ unit-test phần thuần — chuỗi UA và dict proxy):
```python
from crawlfb.stealth import USER_AGENT, STEALTH_JS
from crawlfb.config import Proxy

def test_ua_is_chrome_windows():
    assert "Chrome" in USER_AGENT
    assert "Windows NT" in USER_AGENT

def test_stealth_js_patches_webdriver():
    assert "navigator" in STEALTH_JS
    assert "webdriver" in STEALTH_JS

def test_proxy_to_playwright_dict():
    p = Proxy(server="http://1.2.3.4:8080", username="u", password="p")
    d = p.to_playwright()
    assert d == {"server": "http://1.2.3.4:8080", "username": "u", "password": "p"}
```

- [ ] **Bước 2: Chạy test để xác nhận fail**

Chạy: `cd crawl-fb && python -m pytest tests/test_stealth.py -v`
Kỳ vọng: FAIL — ImportError (module chưa có).

- [ ] **Bước 3: Implement stealth launch**

`crawl-fb/src/crawlfb/stealth.py`:
```python
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


@asynccontextmanager
async def launch_context(cfg: Config) -> AsyncIterator[tuple[BrowserContext, Page]]:
    storage_state = None
    if cfg.storage_state:
        try:
            storage_state = json.loads(open(cfg.storage_state, encoding="utf-8").read())
        except (FileNotFoundError, json.JSONDecodeError):
            storage_state = None

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
            if cfg.storage_state:
                state = await context.storage_state()
                with open(cfg.storage_state, "w", encoding="utf-8") as f:
                    json.dump(state, f)
            await context.close()
            await browser.close()
```

- [ ] **Bước 4: Chạy test để xác nhận pass**

Chạy: `cd crawl-fb && python -m pytest tests/test_stealth.py -v`
Kỳ vọng: PASS (3 tests).

- [ ] **Bước 5: Smoke check thủ công (không unit-test được)**

Chạy: `cd crawl-fb && python -c "import asyncio; from crawlfb.stealth import launch_context; from crawlfb.config import Config; asyncio.run(_smoke())"` — hoặc script tạm mở `https://bot.sannysoft.com/` và in `navigator.webdriver` cùng `navigator.userAgent`.
Kỳ vọng: trang load; `navigator.webdriver` là `undefined`, UA là chuỗi Chrome. Không có substring `HeadlessChrome`.
Lưu ý: cần `pip install -r requirements.txt && playwright install chromium` trước.

- [ ] **Bước 6: Commit**

```bash
git add crawl-fb/src/crawlfb/stealth.py crawl-fb/tests/test_stealth.py
git commit -m "feat(crawl-fb): stealth Playwright launch with proxy and session persistence"
```

---

### Task 3: Capture một response GraphQL thật làm fixture

**Files:**
- Tạo: `crawl-fb/tools/capture_feed.py`
- Tạo: `crawl-fb/tests/fixtures/feed_graphql.json` (sinh ra, commit)
- Tạo: `crawl-fb/tests/fixtures/README.md`

**Interfaces:**
- Dùng: `launch_context(cfg)` (Task 2).
- Sinh ra: `tests/fixtures/feed_graphql.json` — dump thô JSON GraphQL feed của một trang, được Task 4 dùng để chốt mapping trường `RawStory`.

Task này mang tính thực nghiệm: đường dẫn trường GraphQL nội bộ của Facebook không được tài liệu hóa và hay thay đổi. Ta capture một response thật, rồi viết code flatten ở Task 4 dựa trên capture đó. Không có unit test ở đây — deliverable chính là chính fixture.

- [ ] **Bước 1: Viết script capture**

`crawl-fb/tools/capture_feed.py`:
```python
"""One-off: load a public page, dump every /api/graphql/ response to a file."""
import asyncio
import json
import sys
from pathlib import Path
from crawlfb.config import Config
from crawlfb.stealth import launch_context

async def main(page_url: str, out: str) -> None:
    cfg = Config(page_url=page_url, output=out, max_posts=5)
    captured = []
    async with launch_context(cfg) as (_ctx, page):
        async def on_response(resp):
            if "/api/graphql/" in resp.url and resp.status == 200:
                try:
                    body = await resp.json()
                    captured.append({"url": resp.url, "body": body})
                except Exception:
                    pass
        page.on("response", on_response)
        await page.goto(cfg.normalized_page_url(), wait_until="networkidle", timeout=60000)
        await asyncio.sleep(8)  # let the feed settle
    Path(out).write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"captured {len(captured)} responses -> {out}")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
```

- [ ] **Bước 2: Chạy capture với trang tham chiếu**

Chạy: `cd crawl-fb && python tools/capture_feed.py "https://www.facebook.com/CotSongGenZ.Page/" tests/fixtures/feed_graphql.json`
Kỳ vọng: script in `captured N responses`; file chứa JSON với object `body`. Nếu trang hiện login wall thay vì feed, thử lại tắt `--headless` (sửa `Config(... headless=False)` trong script), hoặc chờ lâu hơn — ghi lại kết quả vào fixture README.

- [ ] **Bước 3: Viết tài liệu cho fixture**

`crawl-fb/tests/fixtures/README.md`:
```markdown
# feed_graphql.json

Raw capture of Facebook `/api/graphql/` responses while loading
`https://www.facebook.com/CotSongGenZ.Page/`. Used by `test_normalize.py`
to pin the `RawStory` flattening logic.

Regenerate: `python tools/capture_feed.py "https://www.facebook.com/<PAGE>/" tests/fixtures/feed_graphql.json`

Do not edit by hand. Contains no cookies or tokens — only public feed data.
```

- [ ] **Bước 4: Kiểm tra fixture không chứa secret**

Đọc file sinh ra và xác nhận không chứa token `EAA`, không chứa cookie `c_user`/`xs`, không chứa `access_token`. Nếu có, redact trước khi commit.

- [ ] **Bước 5: Commit**

```bash
git add crawl-fb/tools/capture_feed.py crawl-fb/tests/fixtures/feed_graphql.json crawl-fb/tests/fixtures/README.md
git commit -m "test(crawl-fb): capture real Facebook feed GraphQL as fixture"
```

---

### Task 4: Flatten GraphQL sang RawStory và normalize sang Post

**Files:**
- Tạo: `crawl-fb/src/crawlfb/intercept.py`
- Tạo: `crawl-fb/src/crawlfb/normalize.py`
- Test: `crawl-fb/tests/test_normalize.py`

**Interfaces:**
- Dùng: `crawlfb.models.Post` (Task 1); `tests/fixtures/feed_graphql.json` (Task 3).
- Sinh ra:
  - `extract_stories(response_body: dict) -> list[dict]` — lấy các story node thô từ body response GraphQL.
  - `flatten(node: dict, page_id: str, page_name: str) -> dict` — một dict `RawStory` (hợp đồng bên dưới).
  - `normalize_post(raw: dict, input_url: str, page_name: str) -> Post`.
  - `class FeedInterceptor` — gắn handler `page.on("response")`, gọi `extract_stories` + `flatten`, dedupe theo post id vào buffer có thứ tự (`.posts`).

**Hợp đồng RawStory** (thứ `flatten` sinh ra — ổn định, được tài liệu):
```
{
  "post_id": str, "page_id": str, "author_id": str, "author_name": str,
  "author_profile_url": str, "author_profile_pic": str, "text": str,
  "created_time_iso": str, "created_unix": int,
  "reaction_counts": {"LIKE": int, "LOVE": int, "HAHA": int, "SAD": int},
  "comment_count": int, "share_count": int, "permalink_url": str,
  "media": [ { "thumbnail": str, "__typename": str, "__isMedia": str,
               "accent_color": str, "photo_product_tags": list,
               "photo_image": {"uri": str, "height": int, "width": int},
               "url": str, "id": str,
               "feedback": {"can_viewer_comment": bool, "id": str},
               "ocr_text": str } ]
}
```

- [ ] **Bước 1: Viết test fail trước (schema đích là chuẩn mực)**

`crawl-fb/tests/test_normalize.py`:
```python
import base64
import json
from pathlib import Path
from crawlfb.normalize import normalize_post, feedback_id, top_level_url

RAW = {
    "post_id": "1360424439627222",
    "page_id": "100069790373758",
    "author_id": "100069790373758",
    "author_name": "Cột Sống Gen Z",
    "author_profile_url": "https://www.facebook.com/100069790373758",
    "author_profile_pic": "https://scontent/avatar.png",
    "text": "Tỏ tình xong hắc “hoá” luôn\n\n#cotsonggenzpage",
    "created_time_iso": "2026-08-10T08:40:48.000Z",
    "created_unix": 1786351248,
    "reaction_counts": {"LIKE": 58, "LOVE": 1, "HAHA": 69, "SAD": 9},
    "comment_count": 1,
    "share_count": 1,
    "permalink_url": "https://www.facebook.com/CotSongGenZ.Page/posts/pfbid0Fjq",
    "media": [],
}

def test_feedback_id_is_base64_of_feedback_colon_postid():
    expected = base64.b64encode(b"feedback:1360424439627222").decode()
    assert feedback_id("1360424439627222") == expected

def test_top_level_url_is_computed():
    assert top_level_url("100069790373758", "1360424439627222") == \
        "https://www.facebook.com/100069790373758/posts/1360424439627222"

def test_normalize_post_maps_all_fields():
    post = normalize_post(RAW, "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert post.postId == "1360424439627222"
    assert post.feedbackId == feedback_id("1360424439627222")
    assert post.topLevelUrl == top_level_url("100069790373758", "1360424439627222")
    assert post.facebookId == "100069790373758"
    assert post.user.name == "Cột Sống Gen Z"
    assert post.likes == 137
    assert post.topReactionsCount == 4
    assert post.reactionHahaCount == 69
    assert post.reactionLikeCount == 58
    assert post.reactionSadCount == 9
    assert post.reactionLoveCount == 1
    assert post.inputUrl == "https://www.facebook.com/CotSongGenZ.Page/"
    assert post.facebookUrl == "https://www.facebook.com/CotSongGenZ.Page/"
```

- [ ] **Bước 2: Chạy test để xác nhận fail**

Chạy: `cd crawl-fb && python -m pytest tests/test_normalize.py -v`
Kỳ vọng: FAIL — ImportError (module chưa có).

- [ ] **Bước 3: Implement normalize (thuần, deterministic)**

`crawl-fb/src/crawlfb/normalize.py`:
```python
from __future__ import annotations
import base64
from crawlfb.models import Post, User, Media, PhotoImage, MediaFeedback


def feedback_id(post_id: str) -> str:
    return base64.b64encode(f"feedback:{post_id}".encode()).decode()


def top_level_url(page_id: str, post_id: str) -> str:
    return f"https://www.facebook.com/{page_id}/posts/{post_id}"


def _normalize_media(m: dict) -> Media:
    img = m.get("photo_image") or {}
    fb = m.get("feedback") or {}
    return Media(
        thumbnail=m.get("thumbnail"),
        __typename=m.get("__typename"),
        __isMedia=m.get("__isMedia"),
        accent_color=m.get("accent_color"),
        photo_product_tags=m.get("photo_product_tags") or [],
        photo_image=PhotoImage(uri=img["uri"], height=img.get("height"), width=img.get("width"))
        if img.get("uri") else None,
        url=m.get("url"),
        id=str(m["id"]) if m.get("id") else None,
        feedback=MediaFeedback(
            can_viewer_comment=bool(fb.get("can_viewer_comment", False)),
            id=fb.get("id"),
        ),
        ocrText=m.get("ocr_text"),
    )


def normalize_post(raw: dict, input_url: str, page_name: str) -> Post:
    page_id = str(raw.get("page_id", ""))
    post_id = str(raw.get("post_id", ""))
    reactions = raw.get("reaction_counts") or {}
    post = Post(
        facebookUrl=input_url,
        postId=post_id,
        pageName=page_name,
        url=raw.get("permalink_url") or top_level_url(page_id, post_id),
        time=raw.get("created_time_iso"),
        timestamp=raw.get("created_unix"),
        user=User(
            id=str(raw.get("author_id", "")),
            name=raw.get("author_name", "") or page_name,
            profileUrl=raw.get("author_profile_url", ""),
            profilePic=raw.get("author_profile_pic", ""),
        ),
        text=raw.get("text"),
        comments=int(raw.get("comment_count") or 0),
        shares=int(raw.get("share_count") or 0),
        media=[_normalize_media(m) for m in raw.get("media") or []],
        feedbackId=feedback_id(post_id),
        reactionHahaCount=int(reactions.get("HAHA") or 0),
        reactionLikeCount=int(reactions.get("LIKE") or 0),
        reactionSadCount=int(reactions.get("SAD") or 0),
        reactionLoveCount=int(reactions.get("LOVE") or 0),
        paidPartnership=bool(raw.get("paid_partnership", False)),
        topLevelUrl=top_level_url(page_id, post_id),
        facebookId=page_id,
        inputUrl=input_url,
    )
    post.likes = sum(post.model_dump().get(k, 0) for k in (
        "reactionHahaCount", "reactionLikeCount", "reactionSadCount", "reactionLoveCount",
    ))
    post.topReactionsCount = sum(
        1 for v in (post.reactionHahaCount, post.reactionLikeCount,
                    post.reactionSadCount, post.reactionLoveCount) if v > 0
    )
    return post
```

- [ ] **Bước 4: Chạy test để xác nhận pass**

Chạy: `cd crawl-fb && python -m pytest tests/test_normalize.py -v`
Kỳ vọng: PASS (4 tests).

- [ ] **Bước 5: Implement interceptor + flatten (dựa trên fixture thật)**

`crawl-fb/src/crawlfb/intercept.py`:
```python
from __future__ import annotations
from typing import Optional
from crawlfb.models import Post
from crawlfb.normalize import normalize_post


class FeedInterceptor:
    """Collects posts by watching Facebook's in-browser GraphQL feed responses."""

    def __init__(self, page, page_id: Optional[str] = None, page_name: str = ""):
        self._page = page
        self._page_id = page_id
        self._page_name = page_name
        self._seen: set[str] = set()
        self.posts: list[dict] = []  # RawStory dicts, ordered, deduped

    def attach(self) -> None:
        self._page.on("response", self._on_response)

    async def _on_response(self, resp) -> None:
        if "/api/graphql/" not in resp.url or resp.status != 200:
            return
        try:
            body = await resp.json()
        except Exception:
            return
        for node in extract_stories(body):
            raw = flatten(node, self._page_id or "", self._page_name)
            pid = raw.get("post_id")
            if pid and pid not in self._seen:
                self._seen.add(pid)
                self.posts.append(raw)

    def to_models(self, input_url: str) -> list[Post]:
        return [normalize_post(r, input_url, self._page_name) for r in self.posts]
```

`extract_stories` và `flatten` nằm cùng file, implement dựa trên fixture. Đường dẫn node chính xác phải được chốt bằng cách đọc `tests/fixtures/feed_graphql.json`. Plan không thể viết trước các đường dẫn đó vì chúng là nội bộ không tài liệu của Facebook — người implement phải mở fixture, tìm các story node của feed (chúng mang `post_id`/`node.__typename` kiểu `Story`/`CometFeedStory` và một object `feedback` chứa reaction counts), rồi map vào hợp đồng `RawStory` bên trên. Mọi trường trong hợp đồng phải được điền, mặc định rỗng/0 khi fixture thiếu.

```python
def extract_stories(body: dict) -> list[dict]:
    """Yield raw story nodes from a GraphQL feed response body.

    IMPLEMENTATION NOTE: locate the story nodes in the fixture. Facebook nests
    them under data.feedback / data.actor feeds; each node has a `post_id` and
    a `creation_time`. Return the list of those node dicts.
    """
    raise NotImplementedError("map against tests/fixtures/feed_graphql.json")


def flatten(node: dict, page_id: str, page_name: str) -> dict:
    """Map one raw story node to the RawStory contract (see plan Task 4)."""
    raise NotImplementedError("map against tests/fixtures/feed_graphql.json")
```

- [ ] **Bước 6: Thêm test dựa trên fixture cho extract + flatten**

`crawl-fb/tests/test_normalize.py` — thêm:
```python
from crawlfb.intercept import extract_stories, flatten

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "feed_graphql.json").read_text(encoding="utf-8")
)

def test_extract_stories_finds_at_least_one():
    nodes = []
    for entry in FIXTURE:
        nodes += extract_stories(entry["body"])
    assert len(nodes) >= 1
    assert all("post_id" in flatten(n, "", "") for n in nodes)

def test_flatten_roundtrip_matches_reference_shape():
    post = normalize_post(flatten(extract_stories(FIXTURE[0]["body"])[0], "", "CotSongGenZ.Page"),
                          "https://www.facebook.com/CotSongGenZ.Page/", "CotSongGenZ.Page")
    assert set(post.model_dump().keys()) == set(Post.model_validate({}).model_dump().keys())
```

- [ ] **Bước 7: Chạy full test suite**

Chạy: `cd crawl-fb && python -m pytest -v`
Kỳ vọng: PASS (tất cả test các task).

- [ ] **Bước 8: Commit**

```bash
git add crawl-fb/src/crawlfb/intercept.py crawl-fb/src/crawlfb/normalize.py crawl-fb/tests/test_normalize.py
git commit -m "feat(crawl-fb): intercept feed GraphQL and normalize to Post"
```

---

### Task 5: Humanizer + pagination

**Files:**
- Tạo: `crawl-fb/src/crawlfb/humanizer.py`
- Tạo: `crawl-fb/src/crawlfb/paginate.py`
- Test: `crawl-fb/tests/test_humanizer.py`

**Interfaces:**
- Dùng: `crawlfb.config.Config` (Task 1); `FeedInterceptor` (Task 4).
- Sinh ra: `crawlfb.humanizer.Humanizer`; `async collect_posts(page, interceptor: FeedInterceptor, cfg: Config) -> list[Post]`. Được `cli.py` (Task 7) dùng.

- [ ] **Bước 1: Viết test fail trước**

`crawl-fb/tests/test_humanizer.py` (test phần toán deterministic, không test sleep):
```python
import random
from crawlfb.humanizer import Humanizer

def test_delay_is_never_negative():
    h = Humanizer(base=3.0, jitter=2.0, rng=random.Random(1))
    for _ in range(100):
        assert h.next_delay() >= 1.0

def test_delay_stays_within_base_plus_minus_jitter():
    h = Humanizer(base=3.0, jitter=1.0, rng=random.Random(2))
    delays = [h.next_delay() for _ in range(100)]
    assert max(delays) <= 4.0
    assert min(delays) >= 2.0

def test_scroll_steps_are_positive_and_smaller_than_distance():
    h = Humanizer(base=1.0, jitter=0.5, rng=random.Random(3))
    steps = h.scroll_steps(distance=2000)
    assert all(0 < s <= 600 for s in steps)
    assert sum(steps) >= 2000
```

- [ ] **Bước 2: Chạy test để xác nhận fail**

Chạy: `cd crawl-fb && python -m pytest tests/test_humanizer.py -v`
Kỳ vọng: FAIL — ImportError.

- [ ] **Bước 3: Implement humanizer + pagination**

`crawl-fb/src/crawlfb/humanizer.py`:
```python
from __future__ import annotations
import asyncio
import random


class Humanizer:
    """Randomized pauses and human-like scrolling to avoid bot heuristics."""

    def __init__(self, base: float = 3.0, jitter: float = 2.0,
                 rng: random.Random | None = None):
        self.base = base
        self.jitter = jitter
        self.rng = rng or random.SystemRandom()

    def next_delay(self) -> float:
        return max(0.5, self.base + self.rng.uniform(-self.jitter, self.jitter))

    async def pause(self) -> None:
        await asyncio.sleep(self.next_delay())

    def scroll_steps(self, distance: int) -> list[int]:
        """Break one scroll into several human-like increments."""
        steps = []
        remaining = distance
        while remaining > 0:
            step = self.rng.randint(120, 600)
            step = min(step, remaining)
            steps.append(step)
            remaining -= step
        return steps

    async def human_scroll(self, page, distance: int) -> None:
        for step in self.scroll_steps(distance):
            await page.mouse.wheel(0, step)
            await asyncio.sleep(self.rng.uniform(0.2, 0.7))
        await self.pause()
```

`crawl-fb/src/crawlfb/paginate.py`:
```python
from __future__ import annotations
from crawlfb.config import Config
from crawlfb.humanizer import Humanizer
from crawlfb.intercept import FeedInterceptor
from crawlfb.models import Post


async def collect_posts(page, interceptor: FeedInterceptor, cfg: Config) -> list[Post]:
    """Scroll the timeline until max_posts collected or the feed stalls."""
    human = Humanizer(base=cfg.delay_base, jitter=cfg.delay_jitter)
    stall = 0
    last_count = 0
    while len(interceptor.posts) < cfg.max_posts:
        await human.human_scroll(page, cfg.scroll_distance)
        count = len(interceptor.posts)
        if count == last_count:
            stall += 1
            if stall >= cfg.stall_limit:
                break
        else:
            stall = 0
        last_count = count
    return interceptor.to_models(cfg.normalized_page_url())
```

- [ ] **Bước 4: Chạy test để xác nhận pass**

Chạy: `cd crawl-fb && python -m pytest tests/test_humanizer.py -v`
Kỳ vọng: PASS (3 tests).

- [ ] **Bước 5: Commit**

```bash
git add crawl-fb/src/crawlfb/humanizer.py crawl-fb/src/crawlfb/paginate.py crawl-fb/tests/test_humanizer.py
git commit -m "feat(crawl-fb): humanized delays and scroll pagination"
```

---

### Task 6: JSON writer

**Files:**
- Tạo: `crawl-fb/src/crawlfb/writer.py`
- Test: `crawl-fb/tests/test_writer.py`

**Interfaces:**
- Dùng: `crawlfb.models.Post` (Task 1).
- Sinh ra: `write_posts(posts: list[Post], path: Path) -> int` — trả về số post mới được thêm. Được `cli.py` (Task 7) dùng.

- [ ] **Bước 1: Viết test fail trước**

`crawl-fb/tests/test_writer.py`:
```python
from pathlib import Path
from crawlfb.models import Post
from crawlfb.writer import write_posts

def _post(pid: str) -> Post:
    return Post(postId=pid, pageName="p", text="hi")

def test_write_posts_creates_array_and_dedupes(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), _post("2")], out) == 2
    assert write_posts([_post("2"), _post("3")], out) == 1  # "2" đã có
    data = __import__("json").loads(out.read_text(encoding="utf-8"))
    assert [p["postId"] for p in data] == ["1", "2", "3"]

def test_write_posts_skips_posts_without_id(tmp_path: Path):
    out = tmp_path / "out.json"
    assert write_posts([_post("1"), Post()], out) == 1
```

- [ ] **Bước 2: Chạy test để xác nhận fail**

Chạy: `cd crawl-fb && python -m pytest tests/test_writer.py -v`
Kỳ vọng: FAIL — ImportError.

- [ ] **Bước 3: Implement writer**

`crawl-fb/src/crawlfb/writer.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from crawlfb.models import Post


def _load(path: Path) -> list[dict]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def write_posts(posts: list[Post], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load(path)
    seen = {p.get("postId") for p in existing if p.get("postId")}
    added = 0
    for post in posts:
        if post.postId and post.postId not in seen:
            existing.append(post.model_dump())
            seen.add(post.postId)
            added += 1
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return added
```

- [ ] **Bước 4: Chạy test để xác nhận pass**

Chạy: `cd crawl-fb && python -m pytest tests/test_writer.py -v`
Kỳ vọng: PASS (2 tests).

- [ ] **Bước 5: Commit**

```bash
git add crawl-fb/src/crawlfb/writer.py crawl-fb/tests/test_writer.py
git commit -m "feat(crawl-fb): deduping JSON output writer"
```

---

### Task 7: Nối CLI + chạy end-to-end

**Files:**
- Sửa: `crawl-fb/src/crawlfb/__main__.py` (thay stub)
- Tạo: `crawl-fb/src/crawlfb/cli.py`
- Tạo: `crawl-fb/README.md`

**Interfaces:**
- Dùng: tất cả bên trên.
- Sinh ra: lệnh `python -m crawlfb`. Deliverable cuối.

- [ ] **Bước 1: Implement CLI**

`crawl-fb/src/crawlfb/cli.py`:
```python
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
from crawlfb.config import Config
from crawlfb.stealth import launch_context
from crawlfb.intercept import FeedInterceptor
from crawlfb.paginate import collect_posts
from crawlfb.writer import write_posts


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl public Facebook page posts")
    p.add_argument("--page", required=True, help="public page URL")
    p.add_argument("--output", required=True, help="output JSON path")
    p.add_argument("--max-posts", type=int, default=50)
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--headed", dest="headless", action="store_false",
                   help="run a visible browser (debug/anti-bot fallback)")
    p.add_argument("--proxy", default=None, help="http://user:pass@host:port")
    p.add_argument("--delay-base", type=float, default=3.0)
    p.add_argument("--delay-jitter", type=float, default=2.0)
    p.add_argument("--storage-state", default=None)
    return p.parse_args()


async def run(cfg: Config) -> None:
    async with launch_context(cfg) as (_ctx, page):
        page_name = cfg.page_url.rstrip("/").rsplit("/", 1)[-1]
        interceptor = FeedInterceptor(page, page_name=page_name)
        interceptor.attach()
        await page.goto(cfg.normalized_page_url(), wait_until="domcontentloaded", timeout=60000)
        posts = await collect_posts(page, interceptor, cfg)
    added = write_posts(posts, Path(cfg.output))
    print(f"collected {len(posts)}, wrote {added} new -> {cfg.output}")


def main() -> None:
    cfg = Config.from_args(parse_args())
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
```

`crawl-fb/src/crawlfb/__main__.py`:
```python
from crawlfb.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Bước 2: Chạy end-to-end (kiểm tra deliverable thật)**

Chạy: `cd crawl-fb && python -m crawlfb --page "https://www.facebook.com/CotSongGenZ.Page/" --output output/CotSongGenZ_Page.json --max-posts 10`
Kỳ vọng: in `collected N, wrote N new`; `output/CotSongGenZ_Page.json` là mảng JSON mà bản ghi đầu có cùng tập key top-level như `crawl-fb/CotSongGenZ_Page.json`, với `postId`, `feedbackId` (base64), `topLevelUrl`, `reaction*Count`, `media[].ocrText` được điền ở chỗ Facebook công khai.
Lưu ý: nếu feed hiện login wall, chạy lại với `--headed` và/hoặc thêm `--proxy`. Ghi lại kết quả vào README.

- [ ] **Bước 3: Viết README**

`crawl-fb/README.md`:
```markdown
# crawl-fb

Crawl public Facebook page posts into JSON (Apify "Facebook Posts Scraper" shape).

## Install
pip install -r requirements.txt
playwright install chromium

## Run
python -m crawlfb \
  --page "https://www.facebook.com/CotSongGenZ.Page/" \
  --output output/CotSongGenZ_Page.json \
  --max-posts 50

## Anti-detection knobs
- --proxy "http://user:pass@host:port"   # rotate a residential proxy
- --delay-base 3 --delay-jitter 2        # random pause 1-5s between scrolls
- --headed                               # visible browser if headless is flagged
- --storage-state .storage_state.json    # persist cookies across runs (set in .env)

## Rules to avoid a ban
- One page at a time, never parallel.
- Default delays already slow; don't lower them.
- Reuse the same storage_state.json so FB sees a returning visitor.
- Public pages only. Never reuse FB-ACCESS-TOKEN here — it's for future Graph API enrichment.
```

- [ ] **Bước 4: Chạy lại full suite một lần nữa**

Chạy: `cd crawl-fb && python -m pytest -v`
Kỳ vọng: PASS (tất cả test).

- [ ] **Bước 5: Commit**

```bash
git add crawl-fb/src/crawlfb/__main__.py crawl-fb/src/crawlfb/cli.py crawl-fb/README.md crawl-fb/output/.gitkeep
git commit -m "feat(crawl-fb): CLI wiring and end-to-end run"
```

---

### Task 8: Điểm mở rộng comment (chỉ scaffold — chưa implement)

**Files:**
- Sửa: `crawl-fb/src/crawlfb/models.py`
- Test: `crawl-fb/tests/test_models.py`

Task này chỉ chừa sẵn schema để công việc sau (mở permalink từng post và scrape thread comment) có chỗ ghi. Chưa có code scrape.

- [ ] **Bước 1: Thêm field comment**

Trong `crawl-fb/src/crawlfb/models.py`, thêm vào `Post`:
```python
    comments: list = Field(default_factory=list)
```

Đổi tên count `comments` (số) hiện tại thành `commentsCount` (key `comments` trong JSON tham chiếu hôm nay là count, nhưng tên field sẽ cần chứa list object comment sau này). Để trung thành với shape tham chiếu ở v1, giữ key số serialize là `comments` và đưa list vào key mới `commentsData`:

```python
    comments: int = 0                     # count (reference shape)
    commentsData: list = Field(default_factory=list)  # future per-post comment objects
```

- [ ] **Bước 2: Thêm test khẳng định field tồn tại và rỗng**

Thêm vào `crawl-fb/tests/test_models.py`:
```python
def test_post_has_comments_extension_point():
    post = Post.model_validate(REF)
    assert post.commentsData == []
    assert post.comments == 1
```

- [ ] **Bước 3: Chạy test**

Chạy: `cd crawl-fb && python -m pytest tests/test_models.py -v`
Kỳ vọng: PASS.

- [ ] **Bước 4: Commit**

```bash
git add crawl-fb/src/crawlfb/models.py crawl-fb/tests/test_models.py
git commit -m "feat(crawl-fb): reserve comments extension point on Post"
```

---

## Self-Review

**Phủ spec:**
- Tái tạo chính xác shape JSON tham chiếu — Task 1 (models) + Task 4 (normalize) + test `test_post_parses_reference_json`. Đã phủ.
- Crawl giống Apify (intercept GraphQL trong browser) — Task 3 (capture) + Task 4 (intercept). Đã phủ.
- Hỗ trợ proxy — Task 2 (stealth) + CLI `--proxy`. Đã phủ.
- Delay/chống bot — Task 5 (humanizer) + README rules. Đã phủ.
- Output JSON — Task 6. Đã phủ.
- Comment sau này — Task 8 (extension point). Đã phủ.

**Quét placeholder:** `NotImplementedError` duy nhất nằm ở `extract_stories`/`flatten` (Task 4), là cố ý và được ủy quyền rõ cho fixture — plan nêu rõ người implement phải đọc `tests/fixtures/feed_graphql.json` và chốt đường dẫn, vì nội bộ Facebook không thể biết trước khi capture. Còn lại đều có code cụ thể.

**Nhất quán kiểu:** `Config.normalized_page_url()`, `Proxy.to_playwright()`, `launch_context`, `FeedInterceptor.attach()/to_models()`, `collect_posts`, `write_posts`, `normalize_post`, `feedback_id`, `top_level_url` được dùng với tên và signature nhất quán xuyên suốt các task. `Post.comments` vẫn là count số; `Post.commentsData` là list mở rộng mới.
