# crawl-fb

Crawler that scrapes public Facebook page posts and their comments into JSON
(Apify "Facebook Posts Scraper" shape).

## Crawl pipeline

**Post pass (Phase 1)**:
The first pass — scroll the page's feed and collect posts. No comment work happens here.
_Avoid_: post collection, feed scan

**Comment pass (Phase 2)**:
The second pass — open each collected post's permalink and scrape its comments.
_Avoid_: comment collection

**Cap**:
The maximum number of comments scraped per post (200 by default). A post at or
under the cap is scraped in full; a larger post stops at the cap.
_Avoid_: limit, ceiling

## Content types

**Post**:
A single Facebook page post — the unit of output. One post produces one output record.
_Avoid_: Story (that's the raw internal node)

**Feed**:
The page's `/posts/` tab — the paginated list of posts that Phase 1 scrolls.
_Avoid_: timeline, wall

**Permalink**:
A post's canonical `facebook.com/…/posts/<id>` URL, opened in Phase 2 to read its comments.

**Reel**:
A short-video post whose permalink is `/reel/`; its comments live in a drawer,
not inline. Excluded from output.
_Avoid_: short video, clip

**Video post**:
A post carrying video (`is_video`) whose permalink is `/videos/`; its comments
stay inline. Kept in output.
_Avoid_: film, movie

**Comment**:
A single remark on a post, flattened to `comment_id`, `text`, `author`, `likes`,
`date`, `threading_depth`, `comment_url`.
_Avoid_: reply (a reply is a comment with `threading_depth` > 0)
