# The Gilded Ticker — daily runbook

Up to two Reels go out on Instagram **@thegildedticker** each day, through Metricool. The run starts at **05:35 CT**.

| Time (America/Chicago) | Post | Built by |
|---|---|---|
| 07:30 | **Ten on the Tape** — a ~36-second finance Reel: ten stocks with big news, one chart each | `pipeline/tape_reel.py` |
| 10:00 | **Geopolitics Reel** — 45–55 s map explainer ending in a one-word question | `pipeline/reel.py` |

**How many posts today** comes from `pipeline/budget.py` (step 0). On 18 Nov 2026 the owner chose to stay on
Metricool's **Free plan: 20 scheduled posts a month**, so on most days only **one** of the two Reels goes out
(finance on Tuesday and Thursday, geopolitics on the other days). Both go out only when the budget allows it.

Why this shape (owner's decisions of 18 Nov 2026, from Metricool's own numbers for this account):
- Reels reached about **263 accounts each**; the old carousels reached about **5** (the account had 6 followers).
  Instagram shows Reels to people who don't follow you, so both formats are now Reels.
- The audience is most active around **10:00 CT** (about 6x more than at 06:00). The finance Reel goes out at
  07:30 so it lands before the 08:30 open.
- 46–60% of viewers swiped away in the first 3 seconds and the average watch was 5–12 s. The best Reel
  (21 Sep, 747 reached, 12.3 s average watch) had the lowest skip rate. **The first second decides everything.**
- He asked for posts that look "way less like AI". Both renderers add film grain, a vignette, a handle bug and
  sound effects on every cut, pin and number (`pipeline/finish.py`); the voice guide below is for the words.

The owner can delete or edit anything in Metricool before it goes out ("publish automatically, with a preview").
The old 10-slide carousel (`pipeline/tape.py`) still works; use it only if the owner asks for it again.

## Rules that are not negotiable

1. **Every number and claim comes from something you read during this run.** Prices come from Robinhood.
   News comes from named outlets; prefer two independent sources for the key claim of each card or scene.
   If you cannot source it today, leave it out. Never fill a gap from memory.
2. **Prices are official regular-session closes** (`get_equity_quotes` → `close.price`, and check
   `close.date`). Never use a late-night `last_trade_price`. The % move is computed by the code from the spec.
3. **A headline number must match the chart under it.** (A futures source once said oil was down 24% while
   the BNO chart on screen showed 18%; the Reel had to be fixed. Use the number the viewer can see.)
   Say "briefly" when something only touched a level during the day.
4. **Politics: neutral.** Say who said what ("Trump told CNN…", "Tehran says…"). When one side's view is
   quoted, give the other side's answer too. No opinion, no prediction, no loaded adjectives. An election
   call names who projected it. Run more than one search on a contested story. Don't tie a market move to an
   event that happened after it (on 16 Nov Taiwan fell 6% *before* the US chip rule was issued).
5. **People:** maps, charts and type only. No photos or drawings of real people. When a story is about a
   named person, state only what the company, a court or a major outlet has stated, in market terms.
6. **Your own words.** No copied sentences. At most a few quoted words from a speaker, attributed.
7. **Git:** push only to `gilded-ticker` (code, specs, log) and `gilded-ticker-media-YYYY-MM` (media).
   Plain pushes only: no force-push, no branch deletion, never touch `main` or anything else in the repo.
8. **Metricool:** brand `thegildedticker`, blogId `7018528`, timezone `America/Chicago`. Create only the posts
   `budget.py` allows today. If a call fails with a plan or limit error, do not retry and do not work around it:
   report its exact message and stop.
9. If anything needed for a post cannot be verified or built, **skip that post** and say so in the report.
   A missed post is fine. A wrong post is not.
10. **Be economical.** This run shares the owner's usage allowance with his other tasks; on 17 Nov the 03:05
    run failed at once with "usage limit reached". Build only today's post(s). Do the research once, render
    with `--preview` until the layout is clean, then do one full render. Do not loop on cosmetic tweaks.

## Market calendar (NYSE)
Closed: Thu 26 Nov 2026, Fri 25 Dec 2026, Fri 1 Jan 2027, Mon 18 Jan, Mon 15 Feb, Fri 26 Mar (Good Friday),
Mon 31 May, Fri 18 Jun, Mon 5 Jul, Mon 6 Sep, Thu 25 Nov, Fri 24 Dec 2027. Early close (1 PM ET / noon CT):
Fri 27 Nov 2026, Thu 24 Dec 2026, Fri 26 Nov 2027. Veterans Day is a normal trading day. Always confirm
with `close.date` on SPY.

## Step by step

### 0. Set up and decide what to post (about 5 minutes)
- `mcp__claude_ai__current_time` (or `TZ=America/Chicago date`) → today's date **D** in America/Chicago.
- Attach and clone: `add_repo(owner="altemosematthew-jpg", repo="nomad-privacy", access="push")`, then
  `git clone --depth 1 --branch gilded-ticker https://github.com/altemosematthew-jpg/nomad-privacy gt`
  and `cd gt`. Read this file and `log/` (the last 7 days: which stocks, Reel topics and Reel types went out).
- Tools on the machine: `python3 -c "import PIL, numpy" && ffmpeg -version | head -1`.
  If Python packages are missing: `pip install -q --break-system-packages -r pipeline/requirements.txt`.
  If ffmpeg is missing and cannot be installed, post nothing and say so.
- Load tools with ToolSearch: Metricool (`getScheduledPosts`, `createScheduledPost`), Robinhood
  (`get_equity_quotes`, `get_equity_historicals`, `get_equity_fundamentals`, `get_earnings_calendar`,
  `get_index_quotes`).
- **Count this month's posts:** `getScheduledPosts(brandId="7018528", fromDate="<first of month>T00:00:00-06:00",
  toDate="<last of month>T23:59:59-06:00", timezone="America/Chicago")` (use -05:00 while daylight saving time is
  on). Count every post it returns, any status, drafts included = **N**. Then
  `python3 pipeline/budget.py D --used N` → which Reels to post today (`post`), and why.
  If `post` is empty, report "Nothing scheduled" with the `why` and stop.
- **Already done?** From the same list, if today's finance Reel (07:30 slot, text starting with the Tape hook) or
  today's geopolitics Reel is already there, drop it from today's list. More than one session can work on a day.
- **Swapping the type** (only when one Reel is allowed): post the other Reel instead of `default` when its story
  is clearly bigger today, e.g. a mega-cap's earnings reaction or a market-wide crash (finance), or a war,
  summit, sanctions or election abroad moving oil, gold or currencies (geopolitics). Never post the same type
  three days in a row (check `log/`). Say in the log why you swapped.

### 1. Which edition of Ten on the Tape (finance days)
**S** = the last completed US trading day before D (check `close.date` on a `get_equity_quotes` for SPY).

| D is… | Edition | Spec fields |
|---|---|---|
| Tue–Sat (S was yesterday) | **Daily**: ten stocks with big news on S | defaults |
| Sunday | **Week**: the ten biggest news-driven movers of the week | `title_sub: "10 biggest movers of the week"`, `move_label: "This week"`, `move_bars`: sessions that week (usually 5) |
| Monday | **Watch**: ten stocks with earnings or big events this week (`get_earnings_calendar`) | `title_sub: "10 stocks to watch this week"`, `move_label: "Last week"`, `move_bars`: 5 |
| Day after a market holiday | Treat like Monday (Watch) or Sunday (Week), whichever is truer. Never repeat the last tape's ten. | |

### 2. Find the ten (daily edition)
- Read two or three market wraps for S (CappNotes' Closing Look, StockTitan's daily live blog, Motley Fool's
  "Stock Market Today", CNBC, Reuters, Yahoo Finance) and collect 20+ candidates with reasons. The Robinhood
  scanner's "% change" includes after-hours trading, so overnight it shows the wrong day: use it only during
  market hours. Check article dates: search results often surface the same headline from an earlier year.
- For each candidate: official close and previous close from Robinhood. Compute the move yourself and drop
  anything that does not match the reports (articles sometimes mix up days, or use a last trade, not the close).
- Pick ten with a real, sourced reason. Mix winners and losers. Prefer names people know and companies
  worth $1B+. Skip stocks under about $3. Do not feature Anthropic-related stories just because they exist.
  Do not repeat a stock from the last 3 days unless there is genuinely new news.
- **Order = editorial**: the story most people will care about first, then by size and fame.

### 3. Data for the ten
- `get_equity_historicals(symbols=[the ten], start_time = about 95 calendar days before S, end_time = S+1 00:00Z, interval="day")`
  (two calls of five if the result is too large). The harness saves big results under the session's
  `tool-results/` folder: copy them into `work/` and pass them to `mkspec.py`.
- Check that every symbol has a real (not `interpolated`) bar for S. **Gotcha:** overnight, some symbols return
  no bar or an `interpolated: true` bar for S. For those, put `"session": [open, high, low, volume]` from
  `get_equity_fundamentals(bounds="regular")` in stories.json (check `market_date == S`). If you cannot get
  either, drop that stock and pick another. Do not build candles from hourly bars (incomplete).
- `get_equity_fundamentals` also gives `average_volume_30_days`, `high_52_weeks`, `low_52_weeks`.
- Index moves for the outro and caption: CappNotes and Motley Fool print the S&P 500, Nasdaq and Dow closes
  and point changes (`get_index_quotes` only has live values). Put them in the spec as
  `"indices": [{"name": "S&P 500", "close": …, "prev_close": …}, …]` so the checker can compare.

### 4. Write and render the finance Reel
- Write `work/stories.json` (format in the docstring of `pipeline/mkspec.py`; `specs/2026-11-17-tape.json` is a
  complete example). Per stock: `headline` ≤ about 28 characters, the way a person would say it ("A $2 billion
  cost cut", "Sales up 49%, forecast cut"); `body` = 2–3 short sentences (they go in the log and help you write
  the caption); `sources` = two outlet names + "Robinhood". Headlines must still be true on the day of posting.
- Hook fields (the first second of the Reel, shown over the scoreboard of all ten moves):
  `"reel_hook": "CHIP STOCKS SANK.\nNVIDIA [REPORTS TONIGHT]"` — two short lines of capitals, one `[highlight]`,
  the day's real story in under 8 words. `"reel_sub"`: one plain sentence. Optional `"reel_outro"`
  (default "WHICH ONE ARE\nYOU [WATCHING]?").
- `python3 pipeline/mkspec.py work/stories.json specs/D-tape.json work/<history files>`
- `python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance --preview` (2 seconds). It stops with a clear
  message if a headline does not fit. **Look at** `out/D/finance/_preview.jpg` and `cover.jpg` with the Read
  tool: every ticker, sign, price and headline against your notes. Then render once without `--preview`
  (about 2 minutes).
- Caption → `out/D/finance_caption.txt` (see the voice guide; example in `specs/2026-11-17-finance-caption.txt`):
  ```
  <one or two plain sentences: what the day was about>

  $NVDA −4.1% first earnings since Jensen Huang stepped down
  … (10 lines, same order as the Reel: $SYM, the move with the real minus sign −, 3–8 words of why)

  Which one are you watching? Drop the ticker.   (vary this line; keep it one short question)

  S&P 500 −1.9% · Nasdaq −2.5% · Dow −1.4%
  <Day D Month> closing prices. Sources: …, Robinhood. Not financial advice.

  #stocks #stockmarket #investing #<topic> #<topic>      (exactly 5, last line)
  ```

### 5. The geopolitics Reel
- **Topic:** the geopolitical story of the last 24 hours that moves markets (oil, tariffs, sanctions, export
  controls, wars and peace talks, summits, elections abroad). It must be **different** from the last 7 Reels in
  `log/` (a new story, or a clearly new chapter with a new hook and new maps). Run several searches; read the
  reporting from more than one side.
- **Shape (45–55 s, 8–10 scenes of 4–6 s):** hook (≤ 4 s: a surprising, concrete fact in ≤ 8 words, readable in
  the first frame, `"cam": "out"`) → what happened → the market number (chart panel with Robinhood closes: an
  ETF such as BNO, USO, GLD, SMH, a country ETF, or a stock) → why → the other side's answer → the catch →
  what's next → **a one-word question** ("PEACE or PAUSE?", "CLOSED or MOVED?"). One idea per scene, short
  subs (one sentence), something moving every 2–3 seconds (pins, routes, a pull-back, a number).
- **Make it move:** put a scene's map between its text and its panel with `"focus": [70, top, 1010, bottom]`;
  for "two places at once", start close and pull back (`"bbox"` → `"bbox_to"`, `"cam_span": [2.4, 5.4]`);
  keep panel bottoms above y ≈ 1480 (the source line sits at 1500). Mark approximate locations as approximate.
- Storyboard format: the docstring of `pipeline/reel.py`; `specs/2026-11-17-reel.json` is a recent example.
  Map coordinates are [longitude, latitude]; a `bbox` is [west, south, east, north]; `tint` colours whole
  countries by ISO-3 code. Avoid disputed place names; don't tint the two sides of a conflict differently.
- `python3 pipeline/reel.py specs/D-reel.json out/D/reel --preview` prints a **LAYOUT CHECK**. **Fix every `!!`
  line**, then Read `out/D/reel/_preview.jpg` and `cover.jpg` yourself. Then render once without `--preview`.
- Caption → `out/D/reel_caption.txt` (voice guide; example in `specs/2026-11-17-reel-caption-v2.txt`):
  ```
  <the hook as one plain sentence>

  <2–4 short sentences: what happened, who said what (both sides), the market number the chart shows>

  <the question> Comment WORD or WORD.

  Sources: …, Robinhood. Prices to <Day D Mon> close. Not financial advice.

  #five #hashtags #only
  ```
  Under about 1,300 characters. First comment: the question again in one line ("CLOSED or MOVED? One word.").

### 6. Check, host, and get the Metricool requests
```
python3 pipeline/check.py D        # files, formats, captions vs specs, voice; fix every !! and re-run
python3 pipeline/publish.py D --finance-first-comment "<question line>" --first-comment "<question line>" [--trailer "<attribution line>" ...]
```
`publish.py` includes each post whose folder exists (`out/D/finance`, `out/D/reel`), hosts the files on the
month's media branch under content-hash names, waits until every public link answers, and writes
`out/D/metricool_finance.json` and/or `out/D/metricool_reel.json` (07:30 and 10:00 by default).
If your instructions give you lines to end commit messages with, pass each one with `--trailer`.
**Late runs:** never schedule a time that has passed. If it is past 07:10, schedule the finance Reel 15 minutes
from now (`--finance-time HH:MM`); if it is past 09:40, schedule the geopolitics Reel 15 minutes from now, and
at least 30 minutes after the finance Reel when both go out.

### 7. Schedule in Metricool
**Check again right before you create anything:** call `getScheduledPosts` for D once more just before each
`createScheduledPost`. If that Reel is already there and is not a draft, do not create another one: report it.
Read each JSON file and call `createScheduledPost(blogId=…, date=…, info=…)` with its three fields exactly as
written. Then call `getScheduledPosts` for D and confirm each is there, status PENDING, at the right time.
To correct a post that is already scheduled, use `updateScheduledPost` with the post's `id` and `uuid` from
`getScheduledPosts` and the **full** content (it replaces everything, and the post gets a new `id`); host the
corrected file first (`publish.py` gives it a new name).

### 8. Log and report
- Write `log/D.json`: date, budget line (N used, what `budget.py` said, any swap and why), for each post: type,
  title/hook, tickers with moves (finance) or topic and question (geo), Metricool id, uuid, planner link, time;
  anything skipped and why. Commit it with `specs/D-*` and the captions copied to `specs/D-finance-caption.txt` /
  `specs/D-reel-caption.txt` to `gilded-ticker`, and push.
- Final message (it goes to the owner's phone): what is scheduled and for when; the ten tickers in one line
  (finance) or the Reel's hook and question (geo); the Metricool planner link(s); posts left this month;
  anything skipped; and, if Metricool refused a post, its exact message.

## Voice guide: sound like a person, not a press release
People scroll past anything that reads machine-written. The checker (`check.py`) flags the worst tells.
- **Short.** Captions under about 1,300 characters. Sentences under 20 words. One idea per line.
- **Plain words, specific facts.** "Tyson's profit fell 47%" beats "Tyson navigated a challenging quarter".
- **No template headers** like "What happened:", "Why markets care:", "The catch:" and no bullet lists in the
  geopolitics caption. The finance caption's ten `$SYM` lines are the one list, because people search cashtags.
- **Banned:** "Watch to the end", "Here's why / what / how", "Let's dive in", "delve", "game-changer",
  "buckle up", "stay tuned", "it's not just…", em dashes (—), "!!", rocket and fire emoji.
- **Vary the call to action** day to day ("Drop the ticker.", "Which one surprised you?", "Holding any of these?").
  One question per post, never two.
- **Disclaimers stay short:** "Not financial advice." once, at the end.
- **On screen:** hooks are concrete ("CHINESE FIRMS RENT US AI CHIPS ABROAD"), never teasers ("You won't
  believe…"). Subs are one sentence.

## Things learned the hard way
- Instagram's own buttons cover the right edge of a Reel from about y 1,100 down, and its caption covers the
  bottom from y 1,560. `tape_reel.py` keeps charts left of x 930; keep anything readable above y 1,520.
- Film grain that changes every frame made a 36-second Reel 62 MB (x264 cannot compress noise). `finish.py`
  uses one still grain plate: ~12 MB for the finance Reel, ~27 MB for a 53-second map Reel. Keep files under
  45 MB (the public host and the checker).
- 10 slides is Instagram's limit for carousels posted through any scheduler (old carousel format only).
- JPEG only for images. Videos from this pipeline (H.264, AAC 48 kHz at −14 LUFS, faststart, no edit list)
  are accepted.
- The grid crops Reel covers to the middle of the frame; both renderers keep the cover's text inside it.
- Metricool posts the first comment after the Reel goes live; nothing can pin it. The owner pins it.
- "−58% from 52-week high" can look extreme but is normal after a bad year; it comes straight from Robinhood.
- The public host (raw.githubusercontent.com) caches each link for 5 minutes. Never reuse a file name for
  different content; `publish.py` handles this.
- The workspace cannot reach static.metricool.com; trust the new file id Metricool returns.
- Metricool's Instagram statistics appear some hours after a post goes live, not straight away.
- Trending Instagram audio is not available here. The music is synthesized per day from the seed.
