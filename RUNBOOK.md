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
"Russia's oil, hit from two sides" (his best performer). Do not restyle them.
`specs/2026-11-11-*.json` and `specs/2026-11-11-*-caption.txt` are complete, published worked examples
(carousel https://www.instagram.com/p/DfmcN68iFGz/, Reel https://www.instagram.com/reel/DfmczBRDP0B/).

## Rules that are not negotiable

1. **Every number and claim comes from something you read during this run.** Prices come from Robinhood.
   News comes from named outlets; prefer two independent sources for the key claim of each slide or scene.
   If you cannot source it today, leave it out. Never fill a gap from memory.
2. **Prices are official regular-session closes** (`get_equity_quotes` → `close.price`, and check
   `close.date`). Never use a late-night `last_trade_price`. The % move is computed by the code from the spec.
3. **A headline number must match the chart under it.** (A futures source once said oil was down 24% while
   the BNO chart on screen showed 18%; the Reel had to be fixed. Use the number the viewer can see.)
   Say "briefly" when something only touched a level during the day.
4. **Politics: neutral.** Say who said what ("Trump told CNN…", "Tehran says…"). When one side's view is
   quoted, give the other side's answer too. No opinion, no prediction, no loaded adjectives. An election
   call names who projected it. Run more than one search on a contested story.
5. **People:** maps, charts and type only. No photos or drawings of real people. When a story is about a
   named person, state only what the company, a court or a major outlet has stated, in market terms.
6. **Your own words.** No copied sentences. At most a few quoted words from a speaker, attributed.
7. **Git:** push only to `gilded-ticker` (code, specs, log) and `gilded-ticker-media-YYYY-MM` (media).
   Plain pushes only: no force-push, no branch deletion, never touch `main` or anything else in the repo.
8. **Metricool:** brand `thegildedticker`, blogId `7018528`, timezone `America/Chicago`. Create exactly the
   day's two posts. If a call fails with a plan or limit error, do not retry and do not work around it:
   report it and stop. (The Free plan allows 20 scheduled posts a month; two a day uses that up in about ten days.)
9. If anything needed for a post cannot be verified or built, **skip that post** and say so in the report.
   A missed post is fine. A wrong post is not.
10. **Be economical.** This run shares the owner's usage allowance with his other tasks; on 11 Nov the
    03:05 run was stopped by "usage limit reached". Do the research once, render the Reel with `--preview`
    until the layout is clean, then do one full render. Do not loop on cosmetic tweaks.

## Market calendar (NYSE)
Closed: Thu 26 Nov 2026, Fri 25 Dec 2026, Fri 1 Jan 2027, Mon 18 Jan, Mon 15 Feb, Fri 26 Mar (Good Friday),
Mon 31 May, Fri 18 Jun, Mon 5 Jul, Mon 6 Sep, Thu 25 Nov, Fri 24 Dec 2027. Early close (1 PM ET / noon CT):
Fri 27 Nov 2026, Thu 24 Dec 2026, Fri 26 Nov 2027. Veterans Day is a normal trading day. Always confirm
with `close.date` on SPY.

## Step by step

### 0. Set up (about 5 minutes)
- `mcp__claude_ai__current_time` → today's date **D** in America/Chicago.
- Attach and clone: `add_repo(owner="altemosematthew-jpg", repo="nomad-privacy", access="push")`, then
  `git clone --depth 1 --branch gilded-ticker https://github.com/altemosematthew-jpg/nomad-privacy gt`
  and `cd gt`. Read this file and `log/` (the last 7 days: which stocks and Reel topics were used).
- Tools on the machine: `python3 -c "import PIL, numpy" && ffmpeg -version | head -1 && ffprobe -version | head -1`.
  If Python packages are missing: `pip install -q --break-system-packages -r pipeline/requirements.txt`.
  If ffmpeg is missing and cannot be installed, skip the Reel and say so.
- Load tools with ToolSearch: Metricool (`getScheduledPosts`, `createScheduledPost`), Robinhood
  (`get_equity_quotes`, `get_equity_historicals`, `get_equity_fundamentals`, `get_earnings_calendar`,
  `get_index_quotes`).
- **Already done?** `getScheduledPosts(brandId="7018528", fromDate="<D>T00:00:00-06:00",
  toDate="<D>T23:59:59-06:00", timezone="America/Chicago")` (use -05:00 while daylight saving time is on).
  A post counts whether its status is PENDING or PUBLISHED. If today's carousel is there, skip the
  carousel; if today's Reel is there, skip the Reel; if both, report "already scheduled" and stop.

### 1. Which edition of Ten on the Tape
**S** = the last completed US trading day before D (check `close.date` on a `get_equity_quotes` for SPY).

| D is… | Edition | Spec fields |
|---|---|---|
| Tue–Sat (S was yesterday) | **Daily**: ten stocks with big news on S | defaults |
| Sunday | **Week**: the ten biggest news-driven movers of the week | `title_sub: "10 biggest movers of the week"`, `move_label: "This week"`, `move_bars`: sessions that week (usually 5). The chart boxes all of the week's candles and the % is the move over the week. |
| Monday | **Watch**: ten stocks with earnings or big events this week; headline says when ("Reports Wednesday after the close"), body gives what analysts expect (`get_earnings_calendar`) | `title_sub: "10 stocks to watch this week"`, `move_label: "Last week"`, `move_bars`: 5 |
| Day after a market holiday | Treat like Monday (Watch) or Sunday (Week), whichever is truer. Never repeat yesterday's ten. | |

### 2. Find the ten (daily edition)
- Read two or three market wraps for S (Reuters, CNBC, Yahoo Finance, TheStreet, StockTitan's daily movers,
  CappNotes) and collect 20+ candidates with reasons. The Robinhood scanner's "% change" includes
  after-hours trading, so overnight it shows the wrong day: use it only during market hours.
- For each candidate: official close and previous close from Robinhood. Compute the move yourself and drop
  anything that does not match the reports (articles sometimes mix up days).
- Pick ten with a real, sourced reason. Mix winners and losers. Prefer names people know and companies
  worth $1B+. Skip stocks under about $3. Do not feature Anthropic-related stories just because they exist.
  Do not repeat a stock from the last 3 days unless there is genuinely new news.
- **Order = editorial**: the story most people will care about first, then by size and fame.

### 3. Data for the ten
- `get_equity_historicals(symbols=[the ten], start_time = about 95 calendar days before S, end_time = S 00:00Z, interval="day")`.
  The result is large; the harness saves it under `/tmp/claude-tool-results/` — pass that file to `mkspec.py`.
- The bar for S itself: ask again with `start_time = S 00:00Z`, `end_time = S+1 00:00Z`. **Gotcha:** overnight, some
  symbols return no bar or an `interpolated: true` bar for S. For those, put `"session": [open, high, low, volume]`
  from `get_equity_fundamentals(bounds="regular")` in stories.json (check `market_date == S`). Its numbers come
  from a slightly different feed (opens can differ by up to ~2%), so prefer a real daily bar whenever there is one.
  If you cannot get either, drop that stock and pick another. Do not build candles from hourly bars (incomplete).
- `get_equity_fundamentals` also gives `average_volume_30_days`, `high_52_weeks`, `low_52_weeks`.

### 4. Write and render the carousel
- Write `work/stories.json` (format in the docstring of `pipeline/mkspec.py`). Per stock: `headline` ≤ about
  28 characters, written like a person would say it ("A $2 billion cost cut", "Sales up 49%, forecast cut");
  `body` = 2–3 short plain sentences that fit three lines; `sources` = two outlet names + "Robinhood".
  Explain any jargon in five words ("adjusted EBITDA, a measure of profit"). Headlines must still be true on
  the day of posting (count days from D, not from S).
- `python3 pipeline/mkspec.py work/stories.json specs/D-tape.json <history files>`
- `python3 pipeline/tape.py specs/D-tape.json out/D/tape` — it stops with a clear message if text is too
  long or the data does not line up. Fix and re-run.
- **Look at it**: Read `out/D/tape/_sheet_a.jpg` and `_sheet_b.jpg`, then at full size any slide you have
  doubts about. Check every ticker, sign, price and headline against your notes.
- Caption → `out/D/tape_caption.txt` (the account's own format; copy `specs/2026-11-11-tape-caption.txt`):
  ```
  Ten on the Tape | 10 stocks with big news

  1. $SYM +x.x%: short reason
  … (10 lines, same order as the slides; use the real minus sign −)

  Swipe for the charts. Which one are you watching? Tell us in the comments.

  The whole market on <day>: S&P 500 −0.4%, Nasdaq −0.7%, Dow −0.3% <five-word reason>.

  Moves are <Day D Month> closing prices. Sources: …, Robinhood.
  Not investment advice. Always do your own research.

  #stocks #stockmarket #investing #earnings #stocknews      (exactly 5 hashtags, last line)
  ```
  If you mention the indices, add them to the spec as
  `"indices": [{"name": "S&P 500", "close": …, "prev_close": …}, …]` (from `get_index_quotes` or SPY/QQQ/DIA
  closes) so the checker can compare.

### 5. The Reel
- **Topic:** the geopolitical story of the last 24 hours that moves markets (oil, tariffs, sanctions, wars
  and peace talks, summits, elections abroad). It must be **different** from the last 7 Reels in `log/`
  (a new story, or a clearly new chapter with a new hook and new maps). Run several searches; read the
  reporting from more than one side.
- **Shape (45–60 s, 6–8 scenes of 5–9 s):** hook (a surprising fact in ≤ 8 words, readable in the first
  second) → why it matters → the market number (chart panel with Robinhood closes: an ETF such as BNO,
  USO, GLD, SPY, a country ETF, or a stock) → why → the catch → what's next → **a one-word question**
  ("PEACE or PAUSE?", "DEAL or NO DEAL?") with the handle. One idea per scene. Headlines are two lines of
  capitals with one `[highlighted]` phrase. Every scene has a small source line (`src`).
- **Make it move.** Text-heavy scenes lose people. Prefer pins, routes and arcs on the map over a list:
  - the hook scene gets `"cam": "out"` (fast push-in from the first frame);
  - put a scene's map between its text and its panel with `"focus": [70, top_of_map, 1010, bottom_of_map]`;
  - for "two places at once", start close and pull back: `"bbox"` = the first place, `"bbox_to"` = the wide
    view, `"cam_span": [2.4, 5.4]`, and time the far pins to appear after the pull-back ends;
  - panels: keep the bottom above y ≈ 1480 (the source line sits at 1500).
- Storyboard format: the docstring of `pipeline/reel.py`; copy `specs/2026-11-11-reel.json` and change it.
  Map coordinates are [longitude, latitude]; a `bbox` is [west, south, east, north]; `tint` colours whole
  countries by ISO-3 code. Mark approximate locations as approximate. Avoid disputed place names.
- `python3 pipeline/reel.py specs/D-reel.json out/D/reel --preview` prints a **LAYOUT CHECK** that renders
  every half-second of every scene and lists cut-off text, text in the caption zone and overlapping boxes
  or labels. **Fix every `!!` line**, then Read `out/D/reel/_preview.jpg` and `cover.jpg` yourself (the
  checker cannot judge whether it reads well). Then render once without `--preview` (about a minute).
- Caption → `out/D/reel_caption.txt` (copy `specs/2026-11-11-reel-caption.txt`):
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

### 6. Check, host, and get the Metricool requests
```
python3 pipeline/check.py D          # files, formats, captions vs specs; fix every !! and re-run
python3 pipeline/publish.py D --first-comment "<the question line>" [--trailer "<attribution line>" ...]
```
`publish.py` clones (or starts) the month's media branch next to the repo (`../media`), stores every file
under a content-hash name (`01-3f9c2a1b7e.jpg`, so a link can never serve an old version), commits, pushes,
waits until every public link answers, and writes `out/D/metricool_tape.json` and `out/D/metricool_reel.json`.
If your instructions give you lines to end commit messages with, pass each one with `--trailer`.
Skip a post with `--tape none` or `--reel none`. If it is already past 05:50, add
`--tape-time HH:MM --reel-time HH:MM` (carousel 15 minutes from now, Reel 10 minutes after it). Never
schedule a time that has already passed.

### 7. Schedule in Metricool
**Check again right before you create anything.** More than one session can work on the same day (the
03:05 run, a run the owner starts by hand, a chat session), so call `getScheduledPosts` for D once more
just before each `createScheduledPost`. If a carousel (or a Reel) for D is already there and is not a
draft, do not create another one: report it instead. (On 11 Nov two sessions both scheduled a 06:00
carousel for the 12th; one had to be turned into a draft.)
Read each JSON file and call `createScheduledPost(blogId=…, date=…, info=…)` with its three fields exactly
as written. Then call `getScheduledPosts` for D and confirm both are there, status PENDING, at the right times.
To correct a post that is already scheduled, use `updateScheduledPost` with the post's `id` and `uuid` from
`getScheduledPosts` and the **full** content (it replaces everything, and the post gets a new `id`); host the
corrected file first (`publish.py` gives it a new name).

### 8. Log and report
- Write `log/D.json`: date, edition, the ten tickers with moves, the Reel title and topic, Metricool ids, uuids
  and planner links, anything skipped and why. Commit it with `specs/D-*` and the two captions copied to
  `specs/D-tape-caption.txt` / `specs/D-reel-caption.txt` to `gilded-ticker`, and push.
- Final message (it goes to the owner's phone): what is scheduled and for when; the ten tickers in one
  line; the Reel's title and question; the two Metricool planner links; anything skipped; and, if Metricool
  refused a post, its exact message.

## Things learned the hard way
- 10 slides is Instagram's limit for carousels posted through any scheduler. The format is exactly ten.
- JPEG only for images. `reel.mp4` from this pipeline (H.264, AAC 48 kHz at −14 LUFS, faststart, no edit
  list) is accepted.
- The grid crops Reel covers to the middle of the frame; `reel.py` already lowers the cover's headline.
- Metricool posts the first comment after the Reel goes live; nothing can pin it. The owner pins it.
- "−58% from 52-week high" can look extreme but is normal after a bad year; it comes straight from Robinhood.
- The public host (raw.githubusercontent.com) caches each link for 5 minutes. Never reuse a file name for
  different content; `publish.py` handles this.
- The workspace cannot reach static.metricool.com; trust the new file id Metricool returns.
- Metricool's Instagram statistics appear some hours after a post goes live, not straight away.
- Trending Instagram audio is not available here. The Reel's music is synthesized per day from the seed.
