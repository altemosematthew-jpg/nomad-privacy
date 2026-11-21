# The Gilded Ticker — Instagram pipeline

This branch (`gilded-ticker`) is separate from the rest of this repository and shares no files or history
with `main`. It holds the code that builds the daily Instagram Reels for @thegildedticker.

- `RUNBOOK.md` — the step-by-step daily procedure, the posting budget and the voice guide. Start here.
- `pipeline/tape_reel.py` — "Ten on the Tape" as a Reel. From 21 Nov 2026: a 26–34 second Reel that opens on the
  day's biggest move and gives 3–5 stocks a chart each (ten stocks in the spec still gives the older 36-second one).
- `pipeline/reel.py` — the map-explainer geopolitics Reel (video, cover and an original synthesized soundtrack).
- `pipeline/finish.py` — film grain, vignette, handle bug and sound effects shared by both Reels.
- `pipeline/budget.py` — how many posts are left on Metricool's Free plan (20 a month) and how to ration them.
- `pipeline/mkspec.py` — turns story notes plus Robinhood price history into the Tape spec.
- `pipeline/check.py` / `pipeline/publish.py` — last checks (formats, captions vs data, voice), hosting and the Metricool requests.
- `pipeline/tape.py` — the original 10-slide carousel (kept in case the owner wants it back).
- `pipeline/fonts/` — open-licensed fonts (SIL OFL; licence texts alongside). `pipeline/geo/` — country
  outlines from Natural Earth (public domain).
- `specs/` — one JSON per post: the prices, wording and sources behind it. `log/` — what went out each day.

Each day's videos and covers are pushed to a sibling branch named `gilded-ticker-media-YYYY-MM` so Metricool
can fetch them from a public link. Metricool keeps its own copy, so once a month is over that month's media
branch can be deleted on GitHub to free the space.
