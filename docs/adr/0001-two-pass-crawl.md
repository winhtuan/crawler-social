# Two-pass crawl: posts, then comments

crawl-fb originally scraped posts and comments in one interleaved pass — while
scrolling the feed it clicked each post's "view more comments" to expand
comments in place. That entangled two independent jobs: the comment clicks
slowed the scroll, starved post collection, and triggered Facebook's anti-bot
(falling as low as 1 post collected). It also lost comments to feed
virtualization, which removes a post's "view more" button once it scrolls
off-screen.

We split the crawl into two passes. Phase 1 scrolls the feed and collects
posts only (no comment work). Phase 2 opens each collected post's permalink
one at a time and scrapes its comments there, where the comment section is
not virtualized away. Post count and comment completeness become independent.

Considered and rejected: switching to mbasic/m.facebook.com HTML parsing,
which counts posts by explicit pagination instead of scroll and reads comments
from a dedicated page. Rejected for now because it is a larger rewrite and
still needs login cookies plus rate-limit handling; the two-pass Playwright
approach keeps the existing feed/GraphQL machinery and fixes both defects
within it.
