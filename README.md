# crawl-fb

Cào bài + comment fanpage Facebook công khai thành JSON, upload lên S3.

## Install

```bash
pip install -r requirements.txt
```

CloakBrowser tự tải binary lần đầu chạy. Không cần `playwright install chromium`.

## Setup

```bash
copy .env.example .env
```

Điền vào `.env`:

- `PROXY_KEY_VALUE` — key KiotProxy để tự đổi proxy mỗi lần chạy.
- `S3_BUCKET_NAME`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` — để upload kết quả.
- `FB_STORAGE_STATE=.storage_state.json` — file cookie session.

`HTTP_PROXY` để trống cũng được, script tự điền mỗi lần chạy.

## Login (bắt buộc)

```bash
python tools/login.py
```

Đăng nhập tay rồi bấm Enter. Lưu cookie `c_user` + `xs`. Thiếu bước này chỉ cào được ~2 post.

## Run

```bash
python run.py --max-posts 10
```

Flow: đổi proxy (KiotProxy) → cào → upload S3. Ctrl+C giữa chừng vẫn upload phần đã cào.

Chạy crawl đơn lẻ (không đổi proxy, không upload):

```bash
python -m crawlfb.cli --page "https://www.facebook.com/Page/" --max-posts 50
```

## Output

- Local: `output/{id}_{run_id}.json`
- S3: `s3://{bucket}/{dd-MM-yyyy}/{id}/{id}_{run_id}.json`

## Tools

- `tools/login.py` — lấy session đăng nhập.
- `tools/rotate_proxy.py` — đổi proxy KiotProxy, ghi `HTTP_PROXY` vào `.env`.
- `tools/upload_s3.py` — upload file run mới nhất lên S3 (`--dry-run` để xem key, không upload).

## Anti-ban

- Mỗi lần 1 page, không chạy song song.
- Giữ delay mặc định (3±2s), đừng hạ thấp.
- Tái dùng cùng `storage_state.json` để FB thấy khách quen.
- Chỉ cào page công khai.
