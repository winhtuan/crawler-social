# feed_graphql.json

Raw capture of Facebook `/api/graphql/` responses while loading
`https://www.facebook.com/CotSongGenZ.Page/`. Used by `test_normalize.py`
to pin the `RawStory` flattening logic.

Capture method (empirical, logged-out session):

- Passive load fires **no** `/api/graphql/` requests — Facebook inlines the
  logged-out feed into the HTML. The capture script opens the reaction-count
  flyout and clicks a post, which triggers the Comet
  `ProfileCometTimelineFeed` graphql batches that carry the stories.
- Each response is a graphql **batch**: several JSON values concatenated with
  no wrapping array (`resp.json()` fails with "Extra data"). The script splits
  them and stores the batch as a list under `body`.

Contents: 2 responses / 24 batch values, including `Story` nodes
(`post_id`, `creation_time`), `TextWithEntities` messages, and `Feedback`
nodes with `reaction_count` / `top_reactions`.

Regenerate: `python tools/capture_feed.py "https://www.facebook.com/<PAGE>/" tests/fixtures/feed_graphql.json`

Do not edit by hand. Contains no cookies or tokens — only public feed data.
