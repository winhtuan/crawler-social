# crawl-fb scheduled crawler — design

Date: 2026-09-03
Status: Draft for review
Scope: `crawl-fb` only. ai-service ingestion and AWS glue are separate workstreams (see Out of scope).

## 1. Goal

Make `crawl-fb` run headless on a configured schedule, crawl its configured page list, upload
results to S3, and require no human. The crawl engine stays a CLI — no HTTP API is added.

The only communication with ai-service is through S3: crawl-fb uploads, ai-service pulls new
objects. ai-service never calls crawl-fb, and crawl-fb never calls ai-service.

No rewrite of the crawl logic. Proxy rotation, checkpoint resume, the 3-phase
`_crawl_session` (feed scroll → comments → API backfill), and the comment graphql replay all
stay exactly as they are today.

## 2. Target topology

One rented docker-CPU machine runs the two projects as containers:

```
┌────────────────────── docker-cpu (rented) ──────────────────────┐
│  ┌────────────┐                      ┌──────────────┐            │
│  │  crawl-fb  │      (no network     │  ai-service  │            │
│  │  scheduler │       connection)    │  reads S3    │            │
│  │  + CLI     │                      └──────┬───────┘            │
│  └─────┬──────┘                             │                    │
└────────┼────────────────────────────────────┼────────────────────┘
         │ upload per completed page          │ pull new objects
         ▼                                    ▼
   ┌────────────────────────────────────────────────────┐
   │                S3 bucket (crawler-social)          │
   └────────────────────────────────────────────────────┘
```

- **crawl-fb**: self-schedules from `schedule.json`, crawls its page list, uploads each
  finished page's output to S3. Nothing else.
- **ai-service**: reads new S3 objects (its own Lambda / trigger workstream) and runs tier-2.
- The two containers share a machine but need no docker network between them — the S3 bucket
  is the interface.

## 3. Out of scope (separate workstreams)

1. The S3→ai-service trigger (Lambda / notification) and ai-service ingestion + tier-2. This
   spec defines the S3 write contract they consume.
2. Any HTTP API, API Gateway, auth, or job/control surface for crawl-fb. None exists.
3. Multi-instance crawl-fb or distributed state.

## 4. What changes

The crawl core is untouched. Three additions:

1. **Scheduler** — a new thin entrypoint that runs the existing CLI crawl on a cron schedule.
2. **S3 upload per page** — after each page completes, upload its output file to S3.
3. **Config + Docker** — `schedule.json`, and a Dockerfile/compose to run headless on the
   rented machine.

`run.py` and `crawl.bat` remain usable for a manual one-off debug crawl.

## 5. Scheduler

- New entrypoint `python -m crawlfb.scheduler` (a small loop), reading `schedule.json`:

  ```json
  {"enabled": true, "cron": "0 2 * * *"}
  ```

- On each fire it runs the same crawl the CLI runs today — the full configured page list
  (`data/fb_pages.json`), headless, with the current `.env` proxy/storage/aws settings.
- Overlap guard: if a crawl is still running when the next fire arrives, skip and log. One
  crawl at a time (one browser).
- Reload `schedule.json` when it changes (mtime poll), so the schedule can be edited without
  restarting the container.
- Implementation: `croniter` to compute the next fire time + a `while`/`asyncio.sleep` loop.
  No external scheduler dependency (no APScheduler, no host cron) — keeps the footprint small
  and the schedule fully self-contained in the repo.

## 6. Page list

`data/fb_pages.json` stays the single source of truth, mounted as a volume. ai-service (or
ops) edits the file to add/remove pages for the next run; the next scheduled crawl picks it
up. No API needed — the file is the config.

## 7. S3 write contract

Reuses `tools/upload_s3.py` (env `AWS_*`, bucket `crawler-social`), called after each page.

- **Per completed page**: upload `output/{pid}_{run_ts}.json` (today's CLI output file) to key
  `raw/{page_id}/{run_ts}_{job_id}.json`, where `run_ts` = `YYYYMMDD_HHMMSS` and `job_id` = a
  short id for this run. A new run ⇒ a new key ⇒ a new object ⇒ the S3 trigger fires. A repeat
  of the same page in a later run does not overwrite an existing object.
- **On run finish**: write `raw/run_{job_id}/manifest.json` listing
  `{job_id, started_at, finished_at, pages: [{page_id, key, post_count, status, error?}]}`.
  ai-service uses it to tell a complete run from a partial one and to detect skipped pages.

This layout is the interface contract. Workstream 2 (ai-service trigger) keys off new objects
under `raw/` and reads the manifest to know when a run is complete.

## 8. Config & secrets

- `.env` as today: `HTTP_PROXY`, `PROXY_KEY_VALUE`, `FB_STORAGE_STATE`,
  `FB_MAX_POSTS`/`FB_DELAY_*`, `AWS_*`. No new env keys.
- `FB_STORAGE_STATE` holds the cookie session (`c_user`/`xs`) — secret. Mounted as a volume
  into the container, never baked into the image.
- `schedule.json` and `data/fb_pages.json` live under a mounted config volume too, so
  ai-service/ops edit them without rebuilding.

## 9. Docker

- `Dockerfile` in crawl-fb: multi-stage, `python:3.13-slim`, install Playwright chromium +
  system deps, non-root user, `HEALTHCHECK`, `.dockerignore`. Non-root + headless Chromium
  needs `--no-sandbox` or a setuid chromium helper — decide at implementation; the browser
  launch path in `stealth.py` may need a flag.
- `docker-compose.yml`: service `crawl-fb` (scheduler as the default command) with secret and
  config volumes, env from `.env`. ai-service is managed by its own compose; the two need no
  shared network.

## 10. Error handling & edge cases

- A page crawl failure ⇒ log, continue to the next page; the run does not abort. Failed pages
  are recorded in the manifest.
- S3 upload failure after a page crawl ⇒ log and continue; that page's upload self-heals on the
  next scheduled run (new key).
- Overlapping scheduled fire ⇒ skip + log.
- Malformed `schedule.json` ⇒ log error, keep the last known schedule, do not crash.

## 11. Testing

- Existing 109 tests stay green (the crawl core is untouched).
- New tests: schedule next-fire computation (croniter), overlap guard, malformed schedule
  fallback.
- S3 contract test: given a fake output dir, assert the exact keys generated and the manifest
  shape (mock the upload callable, no real S3).

## 12. Migration

1. Add the scheduler entrypoint + `schedule.json` example.
2. Wire per-page S3 upload (reuse `tools/upload_s3.py`).
3. Add Dockerfile + compose; verify headless Chromium runs as non-root.
4. Run on the rented docker-CPU machine; confirm ai-service sees new objects on the next
   scheduled run.

## 13. Open decisions for implementation

- Sandbox handling for non-root Chromium in the container.
- Whether the S3 trigger fires per page (partial-run ingestion) or ai-service waits for the run
  manifest. Belongs to workstream 2; the crawl-fb layout (section 7) supports both.
