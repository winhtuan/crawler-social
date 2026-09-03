# tools/

Các script hỗ trợ cho `crawl-fb`. Hai loại:

## Operational — chạy trong pipeline

| Script | Vai trò | Gọi bởi |
| ------ | ------- | ------- |
| `rotate_proxy.py` | Xoay KiotProxy, ghi `HTTP_PROXY` mới vào `.env` | `run.py` (đầu run + mỗi session) |
| `upload_s3.py` | Upload file output lên S3 | `run.py` (sau crawl) |

## Manual — chạy tay khi cần

| Script | Vai trò |
| ------ | ------- |
| `login.py` | Mở browser hiển thị, login tay, lưu cookie (`c_user`/`xs`) vào `.storage_state.json` |
| `capture_feed.py` | One-off: bắt response `/api/graphql/` để tái tạo `tests/fixtures/feed_graphql.json` |

## Ghi chú

- `fb_dtsg`/`lsd`/`__dyn`/`__csr` **không** do script nào lưu — bắt fresh mỗi
  session trong `src/crawlfb/comment_api.py` (`GraphQLForm`), từ comment root
  query đầu tiên.
- `login.py` dùng `HTTP_PROXY` trong `.env`; proxy hết hạn (~30 phút) thì chạy
  `rotate_proxy.py` trước.
