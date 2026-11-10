# Strike Finder

Options scanner for US stocks. For every listed call, put and vertical spread on the watchlist it computes the expected value after the bid/ask cost, simulates a trade plan (take profit, stop, time limit) on price paths to get an honest win rate, grades it against absolute checks, and hands the exact order to Robinhood. Nothing here places orders.

**The honest bottom line:** no scanner makes options win almost every time. Options are priced close to fair, so the average trade loses roughly its trading cost. High win rates (selling premium) come with average losses several times the average win. The page shows expected value next to the win rate, and the track record measures how its own picks actually did.

## Where it runs

| Where | Data | Notes |
|---|---|---|
| Claude artifact | **Robinhood real-time** for the whole watchlist (re-quoted every minute in market hours), plus My positions and a private **My trades** journal | Needs the Robinhood connector; calls run in your browser with your login. Claude's page security blocks outside servers, so the track record isn't shown there |
| https://strike-finder.onrender.com | Cboe delayed (15 min), 24 symbols, price history, consistency stats, **track record** | Free tier: first load after idle takes ~45 s. The Mac copy pings it every 10 min |
| Mac mini, http://127.0.0.1:8765 | Same as the public server, no cold start | `Start Options Finder.command` / `Stop Options Finder.command` |

## The model (src/engine.js)

- **Fills:** limit orders assumed to fill halfway between the mid and the natural price, in and out.
- **Implied vol:** inverted from each contract's own mid against the stock price the options themselves imply (put-call parity on near-the-money pairs), so call and put IVs at a strike agree. The page flags the symbol when that price is more than 2.5% from the stock quote (a delayed feed, an earnings gap). Term structure, 30-day IV and event detection use the same mid-implied vols.
- **Forecast vol:** 60% implied, 40% realized, where realized is an HAR-style blend (Corsi 2009) of 5-, 20- and 60-day realized vol with jump days removed (weights 0.15 / 0.50 / 0.35), applied as one scale factor to the whole smile (no claim about skew). Scheduled events keep the market's implied jump, capped at 85% of a leg's implied variance.
- **Events:** earnings calendar (Robinhood live, else a built-in list) and forward-variance spikes that stand out from neighbouring expiries and imply at least a 3% move (single stocks only; under-5-day expiries need a huge spike).
- **EV:** value under the forecast minus the fill price, held to expiry, per dollar at risk (premium for buys and short singles, max loss for credit spreads).
- **Plan simulation:** each leg follows its own price path driven by the same daily market shocks, at its own forecast diffusive vol plus its share of the event jump, and is repriced at its own market IV (rising into the event, crushed after); exits pay the fill cost; P/L in today's dollars. This keeps skew from leaking in as fake profit: a fairly priced option or spread averages zero (checked across strikes, skews, events and seeds).
- **Odds (most likely to profit):** the plan re-simulated in several worlds and blended into one probability: the forecast (25%), the market's own vol with no forecast edge (20%), vol a fifth calmer (10%) and wilder (10%), the stock drifting ¼σ against the trade (10%), a crash-prone world with Poisson jumps (about three −7% drops in two years at the same total variance, 10%), profit at expiry (15%), plus a 1.5× earnings jump when there is one. The details also show expected shortfall (average of the worst 5% of outcomes, normal and crash-prone) and an overnight gap stress (±3%, ±10% with IV reacting). Shown with a sampling band, the range across worlds, a 0–100 confidence score (wide markets, thin OI, disagreeing data, inferred events, short expiries and disagreeing worlds lower it), the payoff ratio, the break-even win rate and the Kelly fraction. Its own lens ranks by it, kept honest by expected value.
- **Grade:** liquid, EV ≥ about −5%, plan win rate (42% single buys, 40% debit spreads, 60% sales), time window, decay, no earnings inside, trend, and reward/risk for spreads. A = all pass, B = one miss. An A is not an edge: most A-grade buys are within a few percent of fair.
- **Known lean:** the forecast blends in realized volatility, which is usually below implied, so sales look better than buys; the price paths are lognormal with no crashes, so sale win rates are optimistic. Diagnostics (`diag.js`) on live quotes, Nov 4: with forecast vol forced to implied, every category's plan EV equals its entry-plus-exit cost and calls and puts match, so the simulation itself adds no edge.

## What the professionals look at (added Nov 10)

- **Vol premium:** IV30 minus 20-day realized vol in vol points; +2 to +5 is normal (the premium sellers are paid), wider favors selling, negative favors buying.
- **IV rank / percentile:** today's IV in its one-year range. The tracker logs each symbol's 30-day ATM IV every trading day (`ledger.ivlog`); the public site uses the real range once 20+ days exist, and until then both versions use the past year's range of rolling 20-day realized vol as a proxy.
- **Earnings history (Claude version):** close-to-close moves over the last reports from Robinhood history, compared with the implied move. Market-wide only about one report in four beats the implied move; for large caps about one in three.
- **Book risk (My positions):** beta-weighted delta to SPY (dollars per +1% SPY), vega (dollars per vol point), and a −5% SPY day with IV +40%, every leg repriced.
- **Playbooks:** one-click filter+plan sets: Premium seller 45→21 (30–60 DTE, 16–30 delta, take 50%, close by 21 DTE, stop 2× credit), Patient buyer (60–150 DTE, 55–80 delta, +50% / −40% / 45 days), Earnings seller (credit spreads 7–30 DTE on names reporting inside the window, out within 5 days).

## Track record

`.github/workflows/track.yml` runs every trading day at 19:45 UTC (2:45 PM EST / 3:45 PM EDT): `tracker_scan.py` pulls the chains (Cboe directly, else the public server), then `track.js` loads the engine straight out of `index.html`, marks every open pick at today's quotes, closes it per the default plan (+50%/−50%/21 days for buys; keep 50% / stop at a 200% loss / 21 days for sales), and logs the day's top A-grade picks: 4 single buys, 3 debit spreads, 3 credit spreads, one per symbol. The ledger is `track/ledger.json`; the page reads it through `/api/track`. Run it by hand from the Actions tab (dry run by default).

## My trades (Claude version)

Open a contract, then **Track this trade** at the bottom of the details panel saves it with your fill price, the plan's target, stop and close-by date, and the model's win %. **My trades** re-quotes every saved trade from Robinhood, shows P/L, flags when a target, stop or time limit is hit, and keeps score of closed trades against what the model predicted. Trades are stored privately per person in the artifact's own storage (`data/users/<id>/journal/trades/...`); turn it off with `const JOURNAL = false` in `src/app.js`.

## Earnings dates

`.github/workflows/earnings.yml` runs `earnings_fetch.py` daily at 11:00 UTC: next earnings dates from Nasdaq and Yahoo (no keys; a confirmed date beats an estimate, then the earlier date wins) into `earnings.json`. The public site reads it through `/api/earnings` and the tracker reads the file directly; both fall back to the built-in list. The Claude version uses Robinhood's earnings data.

## Diagnostics

Actions → **diag** → Run workflow runs `diag.js` on a fresh scan (read-only): EV and win-rate distributions by type, days and IV, the top picks with every input, and anything that looks like a data artifact.

## Building and deploying

Edit `src/page.html`, `src/engine.js`, `src/app.js`, `src/mobile.css` (phone and narrow-screen rules), then `python3 build.py` → `index.html` (public site, Mac, tracker) and `snapshot.html` (Claude artifact; not committed). Render does **not** auto-deploy on push: Render dashboard → strike-finder → **Manual Deploy → Deploy latest commit**.

## Server endpoints (finder.py, stdlib only)

`/api/scan` (watchlist, cached 120 s) · `/api/chain?symbol=X` · `/api/hist?symbol=X` · `/api/track` · `/api/earnings` · `/api/health`. CORS open.
