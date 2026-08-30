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
