# Reels are excluded from output

A reel (permalink `/reel/`) shows its comments in a drawer, not inline like a
normal post, so the comment scraper undercounts them. Rather than ship posts
with a silently wrong comment list, crawl-fb drops reels from the output
entirely. Regular video posts (`/videos/`) are kept — their comments stay
inline and scrape fully.

Rejected alternative: special-casing the reel drawer to scrape its comments
best-effort. That keeps a reel in the output with a possibly-incomplete
comment list, which is worse than omitting it — a missing reel is honest, a
wrong comment count is not.

## Exception — Phase 3 API backfill

The feed drop above applies to Phase 1 (the in-browser feed scroll). Phase 3
merges the ~3 newest posts from an external API (scrapecreators → apify) and
does **not** filter reels: those providers return reels alongside regular
posts, and dropping them would miss the freshest content. Their comments are
scraped through the `/reel/<id>/` → `/watch/?v=<id>` rewrite
(`comments._reel_to_watch`), which serves the comment section that the
fullscreen `/reel/` player omits. So a reel can appear in the output when it
comes from the API backfill — the exclusion is a feed-collection rule, not a
global invariant.
