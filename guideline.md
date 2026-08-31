# Guideline — chạy crawl-fb

Cào bài + comment fanpage Facebook công khai, ghi JSON vào `output/`. Làm theo thứ tự.

## 1. Cài thư viện

```bash
pip install -r requirements.txt
```

Lần đầu CloakBrowser tự tải binary (vài chục giây). Bản free chạy 1 session/lần.

## 2. Tạo `.env`

```bash
copy .env.example .env
```

Điền:
- `PROXY_KEY_VALUE` — key KiotProxy để tự đổi proxy.
- `S3_BUCKET_NAME` + `AWS_*` — để upload kết quả lên S3.

`HTTP_PROXY` để trống cũng được, script tự điền mỗi lần chạy.

## 3. Lấy session đăng nhập (bắt buộc)

Thiếu bước này chỉ cào được ~2 post. `.storage_state.json` phải có cookie `c_user` + `xs`.

```bash
python tools/login.py
```

Đăng nhập tay xong bấm Enter. Kiểm tra:

```bash
python -c "import json; d=json.load(open('.storage_state.json')); names={c['name'] for c in d['cookies']}; print('c_user' in names, 'xs' in names)"
```

Phải ra `True True`.

## 4. Danh sách page

Sửa `data/fb_pages.json`:

```json
{
  "pages": [
    {
      "id": "cotsongGenZ.YAN",
      "url": "https://www.facebook.com/cotsongGenZ.YAN"
    }
  ]
}
```

## 5. Chạy

```bash
python run.py --max-posts 10
```

Flow: đổi proxy → cào → upload S3. Ctrl+C giữa chừng vẫn upload phần đã cào.

## 6. Kết quả

`output/{id}_{run_id}.json` — mỗi post có `text`, `author`, `reactions`, `comments`, `comments_list`.

Upload lên S3: `s3://{bucket}/{dd-MM-yyyy}/{id}/{id}_{run_id}.json`.
