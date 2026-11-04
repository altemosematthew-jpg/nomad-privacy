# Strike Finder

Options scanner for US stocks. Grades every listed call and put against seven absolute checks, ranks the survivors by the lens you pick, flags earnings, reads your Robinhood positions, and hands the exact contract to Robinhood. Nothing here places orders.

## Where it runs

| Where | Data | Notes |
|---|---|---|
| Claude artifact (shared page) | **Robinhood real-time** for the symbols you load (auto-loads your last set on open, re-quotes every 60 s in market hours) + Cboe 15-min delayed for the rest of the watchlist | Needs your Robinhood connector; calls run in your browser with your login |
| https://strike-finder.onrender.com | Cboe delayed (15 min), 24-symbol watchlist, price history and consistency stats | Free tier: first load after idle takes ~45 s. The Mac copy pings it every 10 min to keep it warm |
| Mac mini, http://127.0.0.1:8765 | Same as the public server, no cold start | `Start Options Finder.command` / `Stop Options Finder.command` |

## Deploying a change

Render does **not** auto-deploy on push. After `git push`: Render dashboard → strike-finder → **Manual Deploy → Deploy latest commit** (about a minute).

The Mac copy serves `index.html` straight from disk, so page changes apply on reload; a `finder.py` change needs Stop/Start.

## Files

- `finder.py` — stdlib HTTP server. `/api/scan` (whole watchlist, cached 120 s), `/api/chain?symbol=X`, `/api/health`. Adds `hist` (SMA20/50/200, HV20/60, 1-/3-month returns) per symbol from Cboe daily history and `h` (per-contract consistency across scans). CORS open so the artifact can read it.
- `index.html` — the page. Falls back snapshot → same-origin server → public server, merges Robinhood real-time on top.
- `watchlist.json` — symbols the server scans. Any other symbol can be typed into the page's Add box.
- `render.yaml` (repo root) — Render blueprint.

## What the numbers mean

See the glossary at the bottom of the page. Short version: **Grade** A clears liquidity, price vs fair, price vs realized vol, odds, time, decay, earnings and trend checks; **vs realized** is a Black–Scholes price at the stock's own 20-day realized volatility versus what you'd pay; **Consistency** is how often the contract has looked under-priced across scans.
