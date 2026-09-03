# crawl-fb as an internal job service — design

Date: 2026-09-03
Status: Draft for review
Scope: `crawl-fb` only. ai-service ingestion and AWS glue are separate workstreams (see Out of scope).

## 1. Goal

Turn `crawl-fb` from a manual CLI crawler into a self-scheduling job service that a colocated
ai-service can configure, that uploads crawl results to S3, and whose engine internals stay
untouched. The crawler must run headless on a schedule without a human.

No rewrite of the crawl logic. Proxy rotation, checkpoint resume, the 3-phase
`_crawl_session` (feed scroll → comments → API backfill), and the comment graphql replay all
stay exactly as they are today.

## 2. Target topology

One rented docker-CPU machine runs two containers on a private docker network:

```
┌────────────────────── docker-cpu (rented) ──────────────────────┐
│  ┌────────────┐   docker network   ┌──────────────┐             │
│  │  crawl-fb  │◀──────────────────▶│  ai-service  │             │
│  │  :8084     │  control API       └──────────────┘             │
│  │  scheduler │                     (pulls S3 itself)           │
│  └─────┬──────┘                                                 │
└────────┼────────────────────────────────────────────────────────┘
         │ upload per completed page
         ▼
   ┌───────────┐  S3 event   ┌──────────────┐
   │ S3 bucket │────────────▶│ Lambda / aws │  workstream 2 (ai-service side)
   │crawler-social           │ pull to      │
   └───────────┘             │ ai-service   │
                             └──────────────┘
```

- **crawl-fb** self-schedules (`schedule.json` cron), crawls its configured page list, uploads
  each finished page's output to S3, and exposes a small control API for ai-service.
- **ai-service** pushes the page list over the docker network and reads results from S3. It
  never downloads crawl output over HTTP.
- AWS (API Gateway, S3 trigger/Lambda) is existing infrastructure on the ai-service side; this
  spec only fixes the S3 object layout crawl-fb writes so the trigger is deterministic.

## 3. Out of scope (separate workstreams)

1. The S3→ai-service trigger (Lambda / notification) and ai-service ingestion + tier-2. This
   spec defines the S3 write contract they consume.
2. The role of the AWS API Gateway; it does not front crawl-fb (colocated ai-service uses the
   docker network).
3. Multi-instance crawl-fb, horizontal scaling, or distributed job state.

## 4. Control API — FastAPI on :8084

Auth: `X-API-Key` header, value from env `CRAWL_API_KEY`. When unset (local dev) auth is
disabled. Runs on the private docker network only; not published to the host unless asked.

| Method | Path | Body | Response | Notes |
|---|---|---|---|---|
| `PUT` | `/pages` | `{"pages":[{"url":"...","id"?:"..."}]}` | `200 {count}` | Replace the whole configured list (persisted JSON). Idempotent replace. |
| `GET` | `/pages` | — | current list | |
| `POST` | `/crawl` | — | `202 {"job_id"}` | Run the full current page list. `409` when a job is already queued/running. |
| `GET` | `/jobs/{id}` | — | `{status, progress, per_page:[...], error?}` | `status ∈ queued\|running\|done\|failed\|cancelled`. |
| `DELETE` | `/jobs/{id}` | — | `202` | Cancel between pages. |
| `GET` | `/jobs/latest` | — | latest job id + status | For ai-service / dashboards to find the newest run. |

`GET /jobs/{id}/result` is intentionally **not** a delivery path. Output lives on S3; the API
returns metadata only. A `result_urls` list of the S3 keys per page may be added to the job
response for debugging.

## 5. Engine refactor

Split the CLI so the crawl core is callable by both the CLI and the API worker, with no
behavior change.

- **`src/crawlfb/engine.py`** (new): `async def crawl_page(cfg: Config, cancel: asyncio.Event) -> int`
  — one page run extracted from today's `_crawl_session`/`run` loop. Takes a `Config` whose
  `output` points at the job directory, and returns the number of posts written. Respects
  `cancel` between posts.
- **`src/crawlfb/cli.py`**: becomes a thin shim — `main()` parses args, builds `Config`,
  calls `engine.crawl_page`, then runs the existing S3 upload via `tools/upload_s3.py`. Kept
  so a human can still do a one-off `--headed` debug crawl and so the old manual flow is a
  regression harness for the engine.
- **`src/crawlfb/api/`** (new): FastAPI app + in-process worker (section 6) + `pages` store +
  `schedule.json` loader (section 7).
- Writer, checkpoint, feed_checkpoint, interceptor modules: **unchanged**. Each job = one
  directory `output/jobs/{job_id}/`; each page writes `{page_id}.json` exactly as today, with
  `job_id` playing the role the run timestamp played.

## 6. Worker & job store

- Job store in memory: `{job_id: {status, pages, started_at, finished_at, error, s3_keys}}`.
- Single worker. Concurrency 1 — one browser, one job. `POST /crawl` returns `409` when a job
  is already queued or running.
- The worker runs in its own thread with its own asyncio loop (`asyncio.run`), so a long crawl
  never blocks the uvicorn event loop.
- On job start: snapshot the current page list into the job record; per page build a `Config`
  (`output = output/jobs/{job_id}/`, headless, env proxy/storage/aws as today) and call
  `engine.crawl_page`.
- After each page completes: upload that page's output file to S3 (section 8) and record the
  key. Failures are recorded per page in `per_page`; a failing page does not abort the job.
- Job record in memory only: a service crash loses the record, but `output/jobs/{job_id}/`
  files survive on disk. A later scheduled run starts a fresh job; no crash-recovery replay in
  v1.
- Cancel: `asyncio.Event` checked between posts and pages inside the engine. Best-effort; the
  page already in flight finishes.

## 7. Scheduler

- Config file `schedule.json` (mounted volume), e.g.
  `{"enabled": true, "cron": "0 2 * * *"}` (cron syntax).
- The API process watches the file; on change it reloads the cron expression (mtime poll or
  file watcher). No restart needed to change the schedule.
- On each fire: if no job is running, trigger the same path as `POST /crawl`. If one is, log
  and skip (overlap guard).
- Running the job in the scheduled slot does not re-read pages at fire time only: it snapshots
  the current page list (as section 6) so a mid-run `PUT /pages` does not mutate a running job.

## 8. S3 write contract

Reuses `tools/upload_s3.py` (env `AWS_*`, bucket `crawler-social`), called from the worker
after each page, not from the CLI.

- **Per completed page**: upload `output/jobs/{job_id}/{page_id}.json` to key
  `raw/{page_id}/{run_ts}_{job_id}.json` where `run_ts` = the job start time `YYYYMMDD_HHMMSS`.
  A new run ⇒ a new key ⇒ a new object ⇒ the S3 trigger fires. A repeat of the same page in a
  later run does not overwrite an existing object.
- **On job finish**: write `raw/run_{job_id}/manifest.json` listing `{job_id, started_at,
  finished_at, pages: [{page_id, key, post_count, status, error?}]}`. Consumed by ai-service /
  dashboards to distinguish a complete run from a partial one and to detect skipped pages.

This layout is the interface contract. Workstream 2 (ai-service trigger) keys off new objects
under `raw/` and reads the manifest to know when a run is complete.

## 9. Config & secrets

- `.env` as today: `HTTP_PROXY`, `PROXY_KEY_VALUE`, `FB_STORAGE_STATE`,
  `FB_MAX_POSTS`/`FB_DELAY_*`, `AWS_*`, plus new `CRAWL_API_KEY`.
- `FB_STORAGE_STATE` holds the cookie session (`c_user`/`xs`) — secret. Mounted as a volume
  into the container, never baked into the image.
- Schedule and page list live under a mounted config volume too, so ai-service/ops edit them
  without rebuilding.

## 10. Docker

- `Dockerfile` in crawl-fb: multi-stage, `python:3.13-slim`, install Playwright chromium +
  system deps, non-root user, `HEALTHCHECK` (GET the app root or `/pages`), `.dockerignore`.
  Non-root + headless Chromium needs `--no-sandbox` or a setuid chromium helper — decide at
  implementation; the browser launch path in `stealth.py` may need a flag.
- `docker-compose.yml`: services `crawl-fb` and `ai-service` on one private network; secret
  and config volumes; env from `.env`/secrets. crawl-fb port not published to host by default.

## 11. Error handling & edge cases

- Page crawl failure ⇒ record in `per_page`, job continues. Job fails only if no page can start
  (e.g. all URLs dead) or the browser cannot launch.
- S3 upload failure after a page crawl ⇒ job stays `running` for later pages but marks that
  page `upload_failed` in `per_page`; a re-run of the same page (next schedule) produces a new
  key, so a lost upload self-heals on the next run.
- `POST /crawl` while running ⇒ `409`. Same-page list empty ⇒ `409` with message.
- Scheduled fire while running ⇒ skip + log.
- Malformed `schedule.json` ⇒ log error, keep last known schedule, do not crash the process.

## 12. Testing

- Existing 109 tests stay green (engine extraction is behavior-preserving).
- New unit tests: pages store (replace/get/persist); schedule loader (parse/reload/malformed);
  overlap guard (409); cancel event propagation.
- New lifecycle test with a fake driver (no real browser): POST /crawl → queued → running →
  done, per-page failure recorded, job still done.
- S3 contract test: given a fake job dir, assert the exact keys generated and the manifest
  shape (no real S3; mock the upload callable).

## 13. Migration

1. Extract `engine.py`; make `cli.py` call it; run full test suite (regression gate).
2. Stand up FastAPI app + worker + pages store behind the engine.
3. Wire scheduler.
4. Wire S3 upload on page completion.
5. Add auth, Dockerfile, compose; verify on the rented docker-CPU machine with ai-service
   colocated.

## 14. Open decisions for implementation

- Sandbox handling for non-root Chromium in the container.
- Whether the S3 trigger fires per page (partial-run ingestion) or ai-service waits for the run
  manifest. This belongs to workstream 2; the crawl-fb layout (section 8) supports both.
