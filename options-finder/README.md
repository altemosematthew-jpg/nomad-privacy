# Strike Finder

Options scanner for US stocks. For every listed call, put and vertical spread on the watchlist it computes the expected value after the bid/ask cost, simulates a trade plan (take profit, stop, time limit) on price paths to get an honest win rate, grades it against absolute checks, and hands the exact order to Robinhood. Nothing here places orders.

**The honest bottom line:** no scanner makes options win almost every time. Options are priced close to fair, so the average trade loses roughly its trading cost. High win rates (selling premium) come with average losses several times the average win. The page shows expected value next to the win rate, and the track record measures how its own picks actually did.

## Where it runs

| Where | Data | Notes |
|---|---|---|
| Claude artifact | **Robinhood real-time** for the whole watchlist (re-quoted every minute in market hours), plus My positions | Needs the Robinhood connector; calls run in your browser with your login. Claude's page security blocks outside servers, so the track record isn't shown there |
| https://strike-finder.onrender.com | Cboe delayed (15 min), 24 symbols, price history, consistency stats, **track record** | Free tier: first load after idle takes ~45 s. The Mac copy pings it every 10 min |
| Mac mini, http://127.0.0.1:8765 | Same as the public server, no cold start | `Start Options Finder.command` / `Stop Options Finder.command` |

## The model (src/engine.js)

- **Fills:** limit orders assumed to fill halfway between the mid and the natural price, in and out.
- **Implied vol:** inverted from each contract's own mid, so the model prices every quote consistently. The stock price is taken from put-call parity when the stock quote and option quotes disagree by more than 2.5% (a delayed feed, an earnings gap).
- **Forecast vol:** 60% implied, 40% realized (20/60-day, jump days removed), applied as one scale factor to the whole smile (no claim about skew). Scheduled events keep the market's implied jump.
- **Events:** earnings calendar (Robinhood live, else a built-in list) and forward-variance spikes between expiries (single stocks only).
- **EV:** value under the forecast minus the fill price, held to expiry, per dollar at risk.
- **Plan simulation:** daily closes on the forecast path plus the event jump; each leg repriced at its own market IV (rising into the event, crushed after); exits pay the fill cost; P/L in today's dollars. Unbiased check: a fairly priced option held to expiry averages ~0.
- **Grade:** liquid, EV ≥ about −5%, plan win rate (42% single buys, 40% debit spreads, 60% sales), time window, decay, no earnings inside, trend, and reward/risk for spreads. A = all pass, B = one miss.

## Track record

`.github/workflows/track.yml` runs every trading day at 19:45 UTC (2:45 PM EST / 3:45 PM EDT): `tracker_scan.py` pulls the chains (Cboe directly, else the public server), then `track.js` loads the engine straight out of `index.html`, marks every open pick at today's quotes, closes it per the default plan (+50%/−50%/21 days for buys; keep 50% / stop at a 200% loss / 21 days for sales), and logs the day's top A-grade picks: 4 single buys, 3 debit spreads, 3 credit spreads, one per symbol. The ledger is `track/ledger.json`; the page reads it through `/api/track`. Run it by hand from the Actions tab (dry run by default).

## Building and deploying

Edit `src/page.html`, `src/engine.js`, `src/app.js`, then `python3 build.py` → `index.html` (public site, Mac, tracker) and `snapshot.html` (Claude artifact; not committed). Render does **not** auto-deploy on push: Render dashboard → strike-finder → **Manual Deploy → Deploy latest commit**.

## Server endpoints (finder.py, stdlib only)

`/api/scan` (watchlist, cached 120 s) · `/api/chain?symbol=X` · `/api/hist?symbol=X` · `/api/track` · `/api/health`. CORS open.
