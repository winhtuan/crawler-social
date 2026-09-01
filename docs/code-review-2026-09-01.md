# Code Review: crawl-fb

Ngày: 2026-09-01
Phạm vi: toàn bộ working tree hiện tại (sạch, không uncommitted change) — 14 module `src/crawlfb/`, 4 `tools/`, `tests/`, `run.py`, `pyproject.toml`, `requirements.txt`, `crawl.bat`, ADR/docs.
Phương pháp: read-only, không git range. Không chạy scraper, không in giá trị secret.

## Verdict

**Chưa merge.** Pipeline coherent, test tốt chỗ quan trọng, khớp phần lớn plan (login gate, proxy rotation, pagination, comment scroll-loading, reel rewrite, S3 upload, Ctrl+C upload). Nhưng 2 Critical + isolation gap phải xử trước khi merge.

---

## Strengths

- **Kiến trúc two-phase hợp lý.** Phase 1 (scroll feed, chỉ post) / Phase 2 (scrape comment từng permalink) / Phase 3 (API backfill) — fix đúng bug feed-virtualization + anti-bot ghi ở `docs/adr/0001-two-pass-crawl.md` ([cli.py:153-211](src/crawlfb/cli.py#L153-L211)).
- **Parsing phòng thủ tốt.** Batch GraphQL nối nhau được tách tay ([intercept.py:29-46](src/crawlfb/intercept.py#L29-L46)), mọi deep lookup null-safe qua `_deep_get`/`_to_int`, comment dedupe first-wins, bỏ qua Relay reference trần ([comments.py:49-62](src/crawlfb/comments.py#L49-L62), `_walk` [171-182](src/crawlfb/comments.py#L171-L182)). Edge case (feed rỗng, thiếu comment, storage_state hỏng/non-dict) đều xử.
- **Crash safety trên đĩa có thật.** `write_posts` upsert theo `post_id`, rewrite file sau mỗi post ([writer.py:16-36](src/crawlfb/writer.py#L16-L36)) — crash giữa run vẫn giữ post đã cào. `run.py:24-30` upload trong `finally` nên Ctrl+C lẫn exception đều chạm S3.
- **Reel→watch rewrite đúng + có test** ([comments.py:229-240](src/crawlfb/comments.py#L229-L240), `test_comments.py:166-175`), comment media marking ([comments.py:104-143](src/crawlfb/comments.py#L104-L143)), most-liked-capped collection ([comments.py:471-473](src/crawlfb/comments.py#L471-L473)).
- **Storage-state handling chắc.** dict/list/scalar đều guard, Cookie-Editor export được convert sang Playwright shape, session lưu lại khi context exit ([stealth.py:47-60, 97-104](src/crawlfb/stealth.py#L47-L60)). Test đầy đủ ở `test_stealth.py`.
- **ResourceMonitor thiết kế tốt** (baseline priming cho `cpu_percent`, pid cache + child discovery, peak tracking), test bằng fake (`monitor.py`).
- **Test fixture-driven cho parsing core** (`test_normalize.py` chạy trên feed thật đã capture). Secret được gitignore + không nằm trong history (đã verify).

---

## Issues

### Critical (Must Fix)

**1. Ctrl+C trong Phase 1 mất sạch post đã cào — đúng scenario mà requirement "still upload what was already crawled" tồn tại.**
- File: [cli.py:174](src/crawlfb/cli.py#L174)
- Vấn đề: post thu vào `interceptor.posts` trong memory, chưa ghi đĩa tới khi Phase 2 bắt đầu ở [cli.py:183](src/crawlfb/cli.py#L183). Phase 1 là đoạn scroll dài. Ctrl+C (hoặc exception) trước lần `write_posts` đầu → mất hết post, không có file cho run_id này, `run.py` upload gì? Tệ hơn: `upload_s3._latest_run_files` ([tools/upload_s3.py:45-57](tools/upload_s3.py#L45-L57)) nhặt file *stale* của run trước và upload nhầm. Message in ra cũng sai: [cli.py:259](src/crawlfb/cli.py#L259) nói "partial output saved" khi chưa ghi gì.
- Fix: checkpoint post Phase 1 vào `cfg.output` ngay khi thu (ghi với `comments_list` rỗng, Phase 2 enrich sau), hoặc trong `finally` của `run()`, flush `interceptor.posts` ra file nếu Phase 2 chưa chạy.

**2. Credential trần trong `todo.md`.**
- File: `todo.md` (đã gitignore, nhưng nằm trong working tree)
- Vấn đề: chứa email + password plaintext của một tài khoản thật. Không nằm trong git history hôm nay, nhưng là credential sống trong project directory — `git add -f`, xoá dòng `.gitignore`, zip/copy folder, share màn hình là lộ.
- Fix: xoá credential khỏi file, đổi password, để vào password manager. Không commit `todo.md`.

### Important (Should Fix)

**3. Một lỗi transient trên một post làm abort cả run.**
- File: [cli.py:125-143](src/crawlfb/cli.py#L125-L143)
- Vấn đề: `_scrape_post_comments` chỉ isolate mỗi `page.goto` (retry ở 125-133); phần còn lại — `page.content()`, `switch_to_all_comments`, `_expand_post_comments`, `collect_comments` — không bọc. Page crash / page đóng / `evaluate` lỗi ở post #5 trong 100 → propagate ra `run()`, giết run, post 6-100 không cào. Mâu thuẫn với intent của chính module ("post bị xoá/private không được đánh chìm run").
- Fix: bọc toàn bộ per-post scrape trong try/except, log-and-continue (ghi post với comment đã capture được, hoặc skip).

**4. Comment interceptor state tăng + scan tuyến tính suốt run.**
- File: [comments.py:258-294](src/crawlfb/comments.py#L258-L294)
- Vấn đề: `CommentInterceptor.by_id`/`post_of` tích luỹ mọi comment từ mọi GraphQL response, `comments_for_post` là O(n) dict-comprehension gọi tới 30× mỗi post (`_expand_post_comments`). Run 100 post × 200 comment = chục nghìn entry, O(n²).
- Fix: bucket theo `post_id` ngay lúc `add_nodes` ([comments.py:272-286](src/crawlfb/comments.py#L272-L286)) vào map `by_post` để `comments_for_post` là O(k); có thể detach/reset interceptor mỗi post để chặn memory.

**5. `.env.example` doc config code không đọc.**
- File: `.env.example:20-23`
- Vấn đề: `FB_DELAY_BASE`, `FB_DELAY_JITTER`, `FB_MAX_POSTS` được doc nhưng không gì đọc — delay/limit chỉ từ argparse default ([cli.py:64, 73-74](src/crawlfb/cli.py#L64)). Operator set `FB_MAX_POSTS=10` trong `.env` vẫn lặng lẽ cào 50.
- Fix: wire các env var này vào `cli.py`/`Config`, hoặc xoá khỏi `.env.example`.

**6. Delay expand comment lặng lẽ vi phạm policy anti-ban.**
- File: [comments.py:380](src/crawlfb/comments.py#L380)
- Vấn đề: guideline ("Giữ delay mặc định 3±2s, đừng hạ thấp") bị `expand_comments` vi phạm — chạy `Humanizer(base=min(cfg.delay_base, 0.8), jitter=0.35)`, cố tình ngắn cho nhanh. Tradeoff ghi ở code comment nhưng không ghi ở `guideline.md`.
- Fix: nếu anti-ban quan trọng, đây là policy deviation cần operator quyết định + ghi lại.

**7. Reel handling mâu thuẫn ADR 0002.**
- File: `docs/adr/0002-exclude-reels.md`, [cli.py:201-211](src/crawlfb/cli.py#L201-L211)
- Vấn đề: ADR 0002 nói reels bị drop, Phase 1 có filter ([paginate.py:59-60](src/crawlfb/paginate.py#L59-L60)). Nhưng Phase 3 API backfill không filter `is_reel`, nên reel post từ scrapecreators/apify quay lại output (comment scrape qua watch rewrite). Cải tiến hợp lý, nhưng ADR + README giờ cũ.
- Fix: cập nhật ADR mô tả exception của API backfill.

**8. `recent.py` không test, comment-scroll fixes không test.**
- File: `recent.py`, [comments.py:306-402, 423-437](src/crawlfb/comments.py#L306-L402)
- Vấn đề: API backfill — retry, dual-provider fallback, hai normalizer ([recent.py:71-152, 198-231](src/crawlfb/recent.py#L71-L152)) — zero coverage. Comment-scroll root-cause fix (`scroll_comment_list`, `_click_view_more`, `switch_to_all_comments`, `expand_comments`) cũng không unit test, dù `_reel_to_watch` (fix nhỏ hơn) có test. Đây là các hàm logic dày + rủi ro cao nhất codebase.
- Fix: test `recent.py` (normalize + retry/fallback qua inject `_http_json`) và comment-scroll JS.

**9. `Proxy.from_url` làm hỏng URL proxy không có port.**
- File: [config.py:19](src/crawlfb/config.py#L19)
- Vấn đề: `f"{parsed.port}"` ra string `"None"` khi URL thiếu port → `server="http://host:None"` (đã repro). URL KiotProxy luôn có port nên path production không ảnh hưởng, nhưng `HTTP_PROXY` viết tay thiếu port làm crawl chết lặng lẽ lúc launch.
- Fix: chỉ nối port khi `parsed.port is not None`.

### Minor (Nice to Have)

- **Dead code**: `Config.from_args` ([config.py:54](src/crawlfb/config.py#L54)), `Humanizer.scroll_steps`/`human_scroll` ([humanizer.py:21-36](src/crawlfb/humanizer.py#L21-L36)), `expand_feed_topdown` ([comments.py:440](src/crawlfb/comments.py#L440)), `_permalink_key`/`_comment_permalink` ([comments.py:220, 243](src/crawlfb/comments.py#L220)) — không dùng trong production. Xoá hoặc wire.
- **`split_json_values` trùng code** nguyên văn giữa `tools/capture_feed.py:10-27` và `intercept.py:29-46` — import thay vì copy.
- **`top_comments` hardcode 1 phần tử** ([normalize.py:42-49](src/crawlfb/normalize.py#L42-L49)) dù là field list số nhiều — intent mơ hồ.
- **`comments` (feed `total_count`) có thể lệch `len(comments_list)`** cùng record ([normalize.py:57](src/crawlfb/normalize.py#L57)). Code comment thừa nhận count không tin được; thêm field `scraped_comments` cho rõ.
- **`write_posts` rewrite cả file JSON mỗi post** ([writer.py:16-36](src/crawlfb/writer.py#L16-L36)) — O(n²) IO cho run lớn. Tradeoff crash-safety chấp nhận được, nhưng lưu ý cho output 100 post/200 comment.
- **`output/` phình không giới hạn** qua các run; `_latest_run_files` chỉ upload run mới nhất. Cân nhắc retention/cleanup.
- **`tools/rotate_proxy.py:97` in full `HTTP_PROXY` URL (gồm `user:pass`) ra console.**
- **`run.py` nuốt mọi child exit code** (`check=False`, `main()` trả `None`) — rotate/crawl/upload lỗi vẫn exit 0, invisible failure trong `.bat`/CI.
- **`crawl.bat:6` hardcode `D:\capstone\brandhub\crawl-fb`**; [cli.py:64](src/crawlfb/cli.py#L64) default `max_posts=50` trong khi "bump lên 100" chỉ đúng qua `crawl.bat`.
- **Không validate login lúc runtime.** `c_user`/`xs` thiếu/stale vẫn launch và lặng lẽ cào ít (~2 post). Startup check cảnh báo khi storage_state thiếu `c_user`/`xs` sẽ chặn được đúng class bug gốc.
- **`pyproject.toml` thiếu `boto3`** (chỉ có trong `requirements.txt`); `pip install .` sẽ `ImportError` ở `tools/upload_s3.py`. `crawlfb.egg-info/requires.txt` cũng stale (thiếu `cloakbrowser`, `boto3`, `psutil`).

---

## Recommendations

1. **Fix Phase-1 checkpoint (Critical #1) trước** — vi phạm trực tiếp requirement.
2. **Isolate per-post failure (Important #3)** — post bị xoá/private hay page error transient phải degrade, không giết run.
3. **Thêm test** cho `recent.py` (normalize + retry/fallback qua inject `_http_json`) và comment-scroll JS — hai vùng chưa test, nhiều logic, chứa các root-cause fix gần đây.
4. **Reconcile docs với code**: cập nhật ADR 0002 cho API-reel backfill, wire hoặc xoá `FB_*` env vars, ghi deviation delay expand comment vào `guideline.md`.
5. **Bound interceptor memory** bằng bucket lúc `add_nodes` + reset per-post (Important #4).
