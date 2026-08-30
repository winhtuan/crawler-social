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
