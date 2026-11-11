# The Gilded Ticker — daily runbook

Two posts go out on Instagram **@thegildedticker** every morning, through Metricool:

| Time (America/Chicago) | Post | Built by |
|---|---|---|
| 06:00 | **Ten on the Tape** — 10-slide finance carousel | `pipeline/tape.py` |
| 06:10 | **Geopolitics Reel** — 45–60 s map explainer with a one-word question | `pipeline/reel.py` |

The owner chose: publish automatically, with a preview. So schedule both posts in Metricool as soon as
they pass your checks, then report. He can delete or edit them in Metricool before 06:00.

Both formats copy posts **already on the account** (he asked for "less like AI, more like what I already
have up"): the 18 Sept 2026 candlestick "Ten on the Tape" and the map-explainer Reels such as
"Russia's oil, hit from two sides" (his best performer). Do not restyle them. `specs/2026-11-11-*.json`
are complete worked examples.

## Rules that are not negotiable

1. **Every number and claim comes from something you read during this run.** Prices come from Robinhood.
   News comes from named outlets; prefer two independent sources for the key claim of each slide or scene.
   If you cannot source it today, leave it out. Never fill a gap from memory.
2. **Prices are official regular-session closes** (`get_equity_quotes` → `close.price`, and check
   `close.date`). Never use a late-night `last_trade_price`. The % move is computed by the code from the spec.
3. **Politics: neutral.** Say who said what ("Trump told CNN…", "Tehran says…"). No opinion, no prediction,
   no loaded adjectives. An election call names who projected it. Run more than one search on a contested
   story so you see how different outlets report it.
4. **People:** maps, charts and type only. No photos or drawings of real people. When a story is about a
   named person, state only what the company, a court or a major outlet has stated, in market terms.
5. **Your own words.** No copied sentences. At most a few quoted words from a speaker, attributed.
6. **Git:** push only to `gilded-ticker` (code, specs, log) and `gilded-ticker-media-YYYY-MM` (media).
   Plain pushes only: no force-push, no branch deletion, never touch `main` or anything else in the repo.
7. **Metricool:** brand `thegildedticker`, blogId `7018528`, timezone `America/Chicago`. If a call fails
   with a plan or limit error, do not retry and do not work around it: report it and stop. (The Free plan
   allows 20 scheduled posts a month; two a day uses that up in about ten days.)
8. If anything needed for a post cannot be verified or built, **skip that post** and say so in the report.
   A missed post is fine. A wrong post is not.

## Step by step

### 0. Set up
- `mcp__claude_ai__current_time` → today's date **D** in America/Chicago.
- Attach the repo: `add_repo(owner="altemosematthew-jpg", repo="nomad-privacy", access="push")`, then
  `git clone --depth 1 --branch gilded-ticker https://github.com/altemosematthew-jpg/nomad-privacy gt`.
  Read this file and `log/` (the last 7 days: which stocks and which Reel topics were used).
- Load tools with ToolSearch: Metricool (`getScheduledPosts`, `createScheduledPost`), Robinhood
  (`get_equity_quotes`, `get_equity_historicals`, `get_equity_fundamentals`, `get_earnings_calendar`).
- **Already done?** `getScheduledPosts(brandId 7018528, D 00:00 → D 23:59)`. If a carousel for today is
  there, skip the carousel. If a Reel is there, skip the Reel. If both, report "already scheduled" and stop.

### 1. Which edition of Ten on the Tape
**S** = the last completed US trading day before D (check `close.date` on a `get_equity_quotes` for SPY).

| D is… | Edition | Spec fields |
|---|---|---|
| Tue–Sat (S was yesterday) | **Daily**: ten stocks with big news on S | defaults |
| Sunday | **Week**: the ten biggest news-driven movers of the week | `title_sub: "10 biggest movers of the week"`, `move_label: "This week"`, `move_bars`: sessions that week (usually 5) |
| Monday | **Watch**: ten stocks with earnings or events this week; headline says when ("Reports Wednesday after the close"), body gives what analysts expect | `title_sub: "10 stocks to watch this week"`, `move_label: "Last week"`, `move_bars`: 5 |
| Day after a market holiday | Treat like Monday (Watch) or Sunday (Week), whichever is truer. Never repeat yesterday's ten. | |

### 2. Find the ten (daily edition)
- Read two or three market wraps for S (Reuters, CNBC, Yahoo Finance, TheStreet, StockTitan's daily movers,
  CappNotes) and collect 20+ candidates with reasons. The Robinhood scanner's "% change" includes
  after-hours trading, so overnight it shows the wrong day: use it only during market hours.
- For each candidate: official close and previous close from Robinhood. Compute the move yourself and drop
  anything that does not match the reports (articles sometimes mix up days).
- Pick ten with a real, sourced reason. Mix winners and losers. Prefer names people know and companies
  worth $1B+. Skip stocks under about $3. Do not feature Anthropic-related stories just because they exist.
- **Order = editorial**: the story most people will care about first, then by size and fame.

### 3. Data for the ten
- `get_equity_historicals(symbols=[the ten], start_time = about 95 calendar days before S, end_time = S 00:00Z, interval="day")`.
  The result is large; the harness saves it under `/tmp/claude-tool-results/` — pass that file to `mkspec.py`.
- The bar for S itself: ask again with `start_time = S 00:00Z`. **Gotcha:** overnight, some symbols return
  no bar or an `interpolated: true` bar for S. For those, use `get_equity_fundamentals(bounds="regular")`:
  `open`, `high`, `low`, `volume`, and check `market_date == S`. If you cannot get a real session bar, drop
  that stock and pick another. Do not build candles from hourly bars (they are incomplete).
- `get_equity_fundamentals` also gives `average_volume_30_days`, `high_52_weeks`, `low_52_weeks`.

### 4. Write and render the carousel
- Write `work/stories.json` (see `pipeline/mkspec.py`). Per stock: `headline` ≤ about 28 characters, written
  like a person would say it ("A $2 billion cost cut", "Sales up 49%, forecast cut"); `body` = 2–3 short
  plain sentences that fit three lines; `sources` = two outlet names + "Robinhood". Explain any jargon in
  five words ("adjusted EBITDA, a measure of profit"). Headlines must still be true on the day of posting
  (count days from D, not from S).
- `python3 pipeline/mkspec.py work/stories.json specs/D-tape.json <history files>`
- `python3 pipeline/tape.py specs/D-tape.json out/D/tape` — it stops with a clear message if text is too
  long or the data does not line up. Fix and re-run.
- **Look at it**: Read `out/D/tape/_sheet_a.jpg` and `_sheet_b.jpg`. Check every ticker, sign, price and
  headline against your notes.
- Caption (this is the account's own format):
  ```
  Ten on the Tape | 10 stocks with big news

  1. $SYM +x.x%: short reason
  … (10 lines; use the real minus sign −)

  Swipe for the charts. Which one are you watching? Tell us in the comments.

  The whole market on <day>: S&P 500 −0.4%, Nasdaq −0.7%, Dow −0.3% <five-word reason>.

  Moves are <Day D Month> closing prices. Sources: …, Robinhood.
  Not investment advice. Always do your own research.

  #stocks #stockmarket #investing #earnings #stocknews      (exactly 5 hashtags)
  ```

### 5. The Reel
- **Topic:** the geopolitical story of the last 24 hours that moves markets (oil, tariffs, sanctions, wars
  and peace talks, summits, elections abroad). It must be **different** from the last 7 Reels in `log/`
  (new story, or a clearly new chapter with a new hook and new maps). Run several searches; read the
  reporting from more than one side.
- **Shape (45–60 s, 6–8 scenes of 5–9 s):** hook (a surprising fact in ≤ 8 words, readable in the first
  second) → why it matters → the market number (chart panel with Robinhood closes: an ETF such as BNO,
  USO, GLD, SPY, a country ETF, or a stock) → why → the catch → what's next → **a one-word question**
  ("PEACE or PAUSE?", "DEAL or NO DEAL?") with the handle. One idea per scene. Headlines are two lines of
  capitals with one `[highlighted]` phrase. Put the source in small type on every scene (`src`).
- Storyboard format: the docstring of `pipeline/reel.py`; copy `specs/2026-11-11-reel.json` and change it.
  Map coordinates are [longitude, latitude]; a `bbox` is [west, south, east, north]; `tint` colours whole
  countries by ISO-3 code. Mark approximate locations as approximate. Avoid disputed place names.
- `python3 pipeline/reel.py specs/D-reel.json out/D/reel --preview`, Read `out/D/reel/_preview.jpg`, fix
  overlaps or cut-off text, then render without `--preview` (about a minute). Read `cover.jpg`.
  Check `ffprobe`: 1080×1920, 30 fps, 45–60 s.
- Caption format:
  ```
  Title | subtitle

  One or two sentences. Watch to the end.

  What happened:
  - …
  Why markets care:      (or "Why oil fell anyway:", etc.)
  - …
  The catch:             (or "Coming up:")
  - …

  <The question> Comment WORD or WORD.

  Prices are closing prices up to <Day D Month>.   (name the fund if a chart uses one)

  Sources: …, Robinhood.

  This is news, not financial advice. Always do your own research.

  #five #hashtags #only
  ```
  First comment: the question again in one line ("PEACE or PAUSE? One word. Then tell me why.").

### 6. Host the media
Metricool fetches media from public links and copies it at scheduling time.
```
git clone --depth 1 --branch gilded-ticker-media-YYYY-MM https://github.com/altemosematthew-jpg/nomad-privacy media
#   (new month and the branch does not exist yet: mkdir media && cd media && git init -b gilded-ticker-media-YYYY-MM
#    && git remote add origin https://github.com/altemosematthew-jpg/nomad-privacy, add a one-line README)
mkdir -p media/D/tape media/D/reel   # copy 01.jpg … 10.jpg, reel.mp4, cover.jpg
git add -A && git commit -m "Media for <date>" && git push origin gilded-ticker-media-YYYY-MM
```
Links: `https://raw.githubusercontent.com/altemosematthew-jpg/nomad-privacy/gilded-ticker-media-YYYY-MM/D/tape/01.jpg`.
The raw host caches for 5 minutes, so **never overwrite a file**: a corrected slide gets a new name (`02b.jpg`).
Check each link returns 200 with `curl -sSI` before scheduling.

### 7. Schedule in Metricool
`createScheduledPost(blogId="7018528", date="<D>T06:00:00<offset>", info=<JSON string>)`
```json
{"autoPublish": true, "descendants": [], "draft": false, "firstCommentText": "", "hasNotReadNotes": false,
 "media": ["…/tape/01.jpg", "… 10 links in order"], "mediaAltText": ["one plain sentence per slide"],
 "providers": [{"network": "instagram"}],
 "publicationDate": {"dateTime": "<D>T06:00:00", "timezone": "America/Chicago"},
 "shortener": false, "smartLinkData": {"ids": []}, "text": "<caption>",
 "instagramData": {"type": "POST", "showReelOnFeed": true}}
```
Reel: same, with `date` / `dateTime` 06:10, `"media": ["…/reel/reel.mp4"]`, `"videoThumbnailUrl": "…/reel/cover.jpg"`,
`"mediaAltText": []`, `"firstCommentText": "<question>"`, `"instagramData": {"type": "REEL", "showReelOnFeed": true}`.
If it is already past 05:50, schedule the carousel 15 minutes from now and the Reel 10 minutes after it.
Then call `getScheduledPosts` for D and confirm both are there with status PENDING and the right times.

### 8. Log and report
- Write `log/D.json`: date, edition, the ten tickers with moves, the Reel title and topic, Metricool ids and
  planner links, anything skipped and why. Commit it with `specs/D-*.json` to `gilded-ticker` and push.
- Final message (it goes to the owner's phone): what is scheduled and for when; the ten tickers in one
  line; the Reel's title and question; the two Metricool planner links; anything skipped; and, if Metricool
  refused a post, its exact message.

## Things learned the hard way
- 10 slides is Instagram's limit for carousels posted through any scheduler. The format is exactly ten.
- JPEG only for images. `reel.mp4` from this pipeline (H.264, AAC, faststart, no edit list) is accepted.
- The grid crops Reel covers to the middle of the frame; `reel.py` already lowers the cover's headline.
- Metricool's first comment may not be applied to Reels, and nothing can pin a comment for him.
- "−58% from 52-week high" can look extreme but is normal after a bad year; it comes straight from Robinhood's 52-week range.
- Trending Instagram audio is not available here. The Reel's music is synthesized per day from the seed.
