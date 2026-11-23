# The Gilded Ticker — daily runbook

Two Reels go out on Instagram **@thegildedticker** every day, through Metricool. The run starts at **05:35 CT**.

## Reels only, new times, a shorter finance Reel (from 21 Nov 2026)
On 20 Nov 2026 the owner asked: "can you make only reels, make the changes necessary to help the account", then
approved the plan ("can you do it now with my approval"). The scheduled task's prompt was rewritten that day. It
says that **where the prompt and this file differ, the prompt wins**. This file was brought into line on 21 Nov.

| Time (America/Chicago) | Post | Built by |
|---|---|---|
| 09:40 | **Ten on the Tape** — a 25–40 s finance Reel: the 3–5 stocks with the biggest news-driven moves | `pipeline/tape_reel.py` (short format) |
| 11:40 | **Geopolitics Reel** — 45–60 s map explainer ending in a one-word question | `pipeline/reel.py` |

- **Finance Reel.** Scene 1 (2.4 s): the single biggest move as a giant number with its ticker and the reason,
  all readable in the very first frame. Then one scene per stock: ticker badge, % move, one-line reason and the
  2-month candlestick chart in a gold frame, then two facts worked out from the spec (volume against normal,
  distance from the 52-week high). Last scene: the question card ("Which one are you watching?"). Put 3, 4 or 5
  stocks in the spec and `tape_reel.py` builds this format (26–34 s). Ten stocks still gives the old 36-second one.
- **Geopolitics Reel.** As described in step 5. Hook rule: the first 2 seconds must show the conflict and one
  hard number on screen, so put the number in scene 1's headline ("3 MISSILES AT RIYADH. …").
- **Late runs.** Never schedule a time that has passed: schedule that Reel 20 minutes from now and the other at
  least 60 minutes after it.
- **No carousels, no feed posts.** `pipeline/tape.py` (the old 10-slide carousel) stays in the repository; use
  it only if the owner asks for it again.

Why (Metricool's numbers, as the task prompt gives them): Reels reach 10–40x more people than the carousels did
(best Reel 909 views, carousels 9–22). The audience is most active 9 AM–noon Central, peak about 10 AM. The Reel
with the lowest skip rate ("Russia's oil, hit from two sides") opened on a clear conflict with a number on screen.


## Discovery: hashtags, keywords and on-screen text (owner's request, 22 Nov 2026)
Instagram caps posts and Reels at 5 hashtags (caption and comments together) and ranks mostly on caption keywords,
on-screen text and the video. So every caption follows these rules (`pipeline/check.py` enforces the starred ones):
- *Exactly 5 hashtags, last line. The first is always `#thegildedticker`.
- *At most one broad tag (#stocks, #stockmarket, #investing, #trading, #finance, #news). The others are specific:
  the company or sector (#nvidia, #chipstocks, #oilprices), the country or theme (#saudiarabia, #tariffs), and a
  niche community tag (#stockmarketnews, #marketnews, #geopoliticsnews, #macroeconomics).
- Never trending or unrelated tags (#fyp, #viral, #explore, #reels): Instagram says they hurt reach.
- *The caption's first line holds searchable words people type: the company name and ticker, and a plain topic
  phrase ("stock market news", "oil prices", "Saudi Arabia"). Keep the hook; add the words to it.
- The Reel's opening title card uses the same key words as the first line (Instagram reads on-screen text).
- Do not delete and repost a Reel to change its tags: edit the caption in the Instagram app instead.

### Posting budget: an open question for the owner (put to him in the 21 Nov report)
The prompt asks for both Reels every day ("create exactly these two Reels"). Metricool's **Free plan still allows
20 scheduled posts a month**. The owner chose to stay on it on 18 Nov, and `pipeline/budget.py` was written then
to ration posts (one Reel on most days) so the account would not go quiet at the end of the month. The new prompt
does not mention that limit.
- **21 Nov:** 13 posts had been used, 7 were left for the 5 trading days to 30 Nov. Both Reels went out, because
  two could be spent without taking a post away from any trading day. That left 5 for 5 trading days.
- From 22 Nov the two instructions pull apart: two a day uses the last posts on Tuesday 24 Nov, and nothing can
  go out from then to 30 Nov. In a full month, two a day lasts 10 days.
- **22 and 23 Nov:** both Reels went out on each day, because the owner had not answered. **19 of 20 are used and
  1 is left** for 24–30 Nov. On 24 Nov only one Reel can be scheduled, then nothing until 1 Dec unless he upgrades.
- **Until the owner answers:** the task prompt is the newer instruction and says it wins, so follow it. Count the
  month's posts in step 0 as before and put "N left this month; at two a day they run out on <date>" at the top
  of the report, every day. If Metricool refuses a post with a plan or limit error: no retry, no workaround,
  report its exact message. When 20 are already used, build nothing and report that. When only one is left,
  build one Reel, not two (rule 10): the day's `default` from `budget.py`, or the other type if its story is
  clearly bigger (the swap rule in step 0), and say in the report that the second was not built because the plan
  has no post left for it.
- **When he answers,** write his answer here, delete this section's other bullets, and if he chooses to ration,
  `budget.py` and the swap rule in step 0 decide again.

Earlier decisions that still hold (18 Nov 2026, from Metricool's numbers for this account):
- 46–60% of viewers swiped away in the first 3 seconds and the average watch was 5–12 s. The best Reel
  (21 Sep, 747 reached, 12.3 s average watch) had the lowest skip rate. **The first second decides everything.**
- He asked for posts that look "way less like AI". Both renderers add film grain, a vignette, a handle bug and
  sound effects on every cut, pin and number (`pipeline/finish.py`); the voice guide below is for the words.

The owner can delete or edit anything in Metricool before it goes out ("publish automatically, with a preview").

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
8. **Metricool:** brand `thegildedticker`, blogId `7018528`, Instagram only, timezone `America/Chicago`. Create
   exactly the two Reels above and nothing else. If a call fails with a plan or limit error, do not retry and do
   not work around it: report its exact message and stop. A media error may be retried once.
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
  `python3 pipeline/budget.py D --used N` → `remaining` and `weekdays_left` for the report (see "Posting budget"
  at the top for what its `post` list means now). If N is 20 or more, report "Nothing scheduled: 20 of 20
  Metricool posts used this month" and stop.
- **Already done?** From the same list, if today's finance Reel (text starting "Ten on the Tape |") or today's
  geopolitics Reel is already there, drop it from today's list. More than one session can work on a day. If both
  are there, report that and stop.
- **Swapping the type** (only if the owner chooses to ration again and one Reel is allowed): post the other Reel instead of `default` when its story
  is clearly bigger today, e.g. a mega-cap's earnings reaction or a market-wide crash (finance), or a war,
  summit, sanctions or election abroad moving oil, gold or currencies (geopolitics). Never post the same type
  three days in a row (check `log/`). Say in the log why you swapped.

### 1. Which edition of Ten on the Tape
**S** = the last completed US trading day before D. On Tuesday to Friday mornings `close.date` on a
`get_equity_quotes` for SPY is S. **On Saturday and Sunday it is still Thursday** (see "Weekend closes" in step 3).

| D is… | Edition | Spec fields |
|---|---|---|
| Tue–Sat (S was yesterday) | **Daily**: the 3–5 stocks with the biggest news-driven moves on S | defaults |
| Sunday | **Week**: the 3–5 biggest news-driven movers of the week (see "Week edition" below) | `move_label: "This week"`, `move_bars`: sessions that week (usually 5) |
| Monday | **Watch**: 3–5 stocks with earnings or big events this week (`get_earnings_calendar`) | `move_label: "Last week"`, `move_bars`: 5 |
| Day after a market holiday | Treat like Monday (Watch) or Sunday (Week), whichever is truer. Never repeat the last tape's stocks. | |

**Week edition (first made 22 Nov 2026; `specs/2026-11-22-tape.json` is the example).**
- Candidates: every stock from the week's daily tapes, the week's earnings (`get_earnings_calendar` with
  `filter="high_market_cap"`) and the big index names. One `get_equity_historicals` call (up to 75 symbols, about
  two weeks of daily bars) gives every Friday-to-Friday move at once. Pick one stock per story.
- With `move_bars` above 1, `tape_reel.py` writes "WEEK TO FRIDAY 20 NOV" in the header, measures volume as the
  week's average against normal, shows "hit a 52-week low" if any session that week touched it, and labels the
  last card "THE WHOLE MARKET, THIS WEEK". Put the week's index closes in `indices` (previous Friday as `prev_close`).
- The single biggest weekly move opens the Reel, so every stock still needs a reason read that morning, and the
  caption says "Moves are for the week, up to Friday D Month closing prices."

**Watch edition (first made in the short format on 23 Nov 2026; `specs/2026-11-23-tape.json` is the example).**
- Candidates: `get_earnings_calendar(start_date=D, days=5, filter="high_market_cap")`, checked against a published
  calendar (StockTitan's "Earnings Calendar for the Week of …" gives day, session and call time). One
  `get_equity_historicals` call for about 20 of them gives every Friday-to-Friday move. Pick five names people know.
- Each card's headline says when the company reports ("Reports Tuesday after the close"). It must fit one line
  if it can: "Reports Wednesday before the open" wraps and leaves one word alone, "Reports Wednesday morning" fits.
- The biggest of last week's five moves opens the Reel. Its hook gives the sourced reason for the fall and the
  report day ("FELL WITH AI STOCKS.\n[EARNINGS ON TUESDAY]"); the sub gives one fact, such as the company's own forecast.
- Analyst estimates differed widely between outlets on 23 Nov (and from Robinhood's), so keep them off the screen
  unless two sources agree. The company's own guidance is safer.
- The caption says "Moves are for last week, up to Friday D Month closing prices."

### 2. Find the three to five (daily edition)
Steps 2–4 were written for ten stocks. The method is the same for three to five: collect many candidates, check
every move yourself, keep the biggest moves that have a real, sourced reason. The single biggest of them opens the
Reel, so its reason has to be the best-sourced one.
- Read two or three market wraps for S (CappNotes' Closing Look, StockTitan's daily live blog, Motley Fool's
  "Stock Market Today", CNBC, Reuters, Yahoo Finance) and collect 20+ candidates with reasons. The Robinhood
  scanner's "% change" includes after-hours trading, so overnight it shows the wrong day: use it only during
  market hours. Check article dates: search results often surface the same headline from an earlier year.
- For each candidate: official close and previous close from Robinhood. Compute the move yourself and drop
  anything that does not match the reports (articles sometimes mix up days, or use a last trade, not the close).
- Pick three to five with a real, sourced reason. Mix winners and losers. Prefer names people know and companies
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
- `get_equity_fundamentals` also gives `average_volume_30_days`, `high_52_weeks`, `low_52_weeks`. The short Reel
  needs all three for every stock (it turns them into the two facts under the chart).
- **Weekend closes.** On Saturday and Sunday `get_equity_quotes` still returns `close.date` = Thursday, because
  the quote only rolls to the next session on Sunday evening. Friday's official close is then the `close_price`
  of Friday's daily bar from `get_equity_historicals`. Use it only after three checks, and say so in the log:
  the bar is not `interpolated` and has volume; the same symbol's Thursday bar equals `close.price` from
  `get_equity_quotes`; and the move you compute matches a published closing move (CappNotes prints two decimals).
  On 21 Nov all thirteen symbols checked this way matched to the cent. `last_trade_price` did not (SPY was $1.10
  away from its close), so never use it. Where a published Friday close can be found (22 Nov): the quote box on any
  Motley Fool article about the stock ("As of 4:00 PM ET 11/20/26"), `fool.com/quote/…` ("Last close" with its
  date), Yahoo Finance's chart page ("At close: November 20 at 4:00:02 PM EST") and news stories that print the
  close. Google Finance, Yahoo's main quote page and Finviz came back stale or blocked; check the date label.
- Index moves for the outro and caption: `get_index_historicals` gives official daily closes for the S&P 500, the
  Nasdaq 100 and the Dow (take the instrument ids from `get_index_quotes(symbols=["SPX","NDX","DJX"])`; DJX is the
  Dow divided by 100). The Nasdaq Composite is not on Robinhood: use the Nasdaq 100 and call it that, or take the
  Composite from CappNotes or Motley Fool. Put them in the spec as
  `"indices": [{"name": "S&P 500", "close": …, "prev_close": …}, …]` so the checker can compare.

### 4. Write and render the finance Reel
- Write `work/stories.json` (format in the docstring of `pipeline/mkspec.py`; `specs/2026-11-17-tape.json` is a
  complete example). Per stock: `headline` ≤ about 28 characters, the way a person would say it ("A $2 billion
  cost cut", "Sales up 49%, forecast cut"); `body` = 2–3 short sentences (they go in the log and help you write
  the caption); `sources` = two outlet names + "Robinhood". Headlines must still be true on the day of posting.
- Hook fields (scene 1, under the giant number of the biggest move; `specs/2026-11-21-tape.json` is an example):
  `"reel_hook": "REUTERS: SEC IS EXAMINING\n[ITS ACCOUNTING]"` — the reason for that move in two short lines of
  capitals with one `[highlight]`, under 8 words, saying who reported it when it is a report. `"reel_sub"`: one
  short plain sentence (it is on screen for 2.4 seconds). Optional `"reel_outro"`
  (default "WHICH ONE ARE\nYOU [WATCHING]?"). The Reel prints `scene 1: $SYM −x.x%` so you can check which stock leads.
- `python3 pipeline/mkspec.py work/stories.json specs/D-tape.json work/<history files>`
- `python3 pipeline/tape_reel.py specs/D-tape.json out/D/finance --preview` (2 seconds). It stops with a clear
  message if a headline does not fit. **Look at** `out/D/finance/_preview.jpg` and `cover.jpg` with the Read
  tool: every ticker, sign, price and headline against your notes. `_first.jpg` is the very first frame: the
  ticker, the number and the reason must all be readable in it. Then render once without `--preview`
  (about 2 minutes).
- Caption → `out/D/finance_caption.txt` (see the voice guide; example in `specs/2026-11-21-finance-caption.txt`):
  ```
  Ten on the Tape | <hook: the biggest move in plain words>

  <one or two plain sentences: what the day was about>

  $NVDA −14.0% the SEC is examining its accounting, Reuters reports
  … (one line per stock, same order as the Reel: $SYM, the move with the real minus sign −, 3–8 words of why)

  Which one are you watching? Comment the ticker.   (the question may vary; it always ends "Comment the ticker.")

  S&P 500 −1.9% · Nasdaq −2.5% · Dow −1.4%
  <Day D Month> closing prices. Sources: …, Robinhood. Not financial advice.

  #thegildedticker #stockmarketnews #<company or sector> #<company or theme> #<niche tag>   (exactly 5, last line; see "Discovery")
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

  #thegildedticker #geopolitics #<country or region> #<market: oil, tariffs, gold…> #<niche tag>   (see "Discovery")
  ```
  Under about 1,300 characters. First comment: the question again in one line ("CLOSED or MOVED? One word.").

### 6. Check, host, and get the Metricool requests
```
python3 pipeline/check.py D        # files, formats, captions vs specs, voice; fix every !! and re-run
python3 pipeline/publish.py D --finance-first-comment "<question line>" --first-comment "<question line>" [--trailer "<attribution line>" ...]
```
`publish.py` includes each post whose folder exists (`out/D/finance`, `out/D/reel`), hosts the files on the
month's media branch under content-hash names, waits until every public link answers, and writes
`out/D/metricool_finance.json` and/or `out/D/metricool_reel.json` (09:40 and 11:40 by default).
If your instructions give you lines to end commit messages with, pass each one with `--trailer`.
**Late runs:** never schedule a time that has passed. If 09:40 has passed, schedule the finance Reel 20 minutes
from now (`--finance-time HH:MM`) and the geopolitics Reel at least 60 minutes after it (`--reel-time HH:MM`).
If only 11:40 has passed, schedule the geopolitics Reel 20 minutes from now.

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
- Final message (it goes to the owner's phone, under 15 lines): what is scheduled and for when; the finance
  Reel's stocks and moves in one line; the geopolitics Reel's title and one-word question; the two Metricool
  planner links; posts left this month and when they run out; anything skipped or uncertain; if Metricool refused
  a post, its exact message; and a reminder that he can delete or edit either Reel in Metricool before it goes out.

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
- In `tape_reel.py`'s first and last scenes text is drawn straight onto the frame, and there Pillow ignores a
  text colour's transparency: text is either absent or fully solid, never half faded (boxes and shapes do fade).
  That is why scene 1 can show everything in the first frame. Do not rely on a text fade in those two scenes.
- Reading pages: the session's fetch helper only opens links that a web search returned in this session. A link
  it finds on a page (or a redirect) is refused, and asking again through a new helper is refused too, so search
  for the page instead. Search results mix years: check every page's date before using it.
- `get_equity_historicals` saves its answer to a file only when it is large. Ask for all the day's symbols in one
  call from about 1 April (about 160 bars each) and it lands in the session's `tool-results/` folder, ready for
  `mkspec.py`, which keeps the last 70 bars.
