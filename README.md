# The Gilded Ticker — Instagram pipeline

This branch (`gilded-ticker`) is separate from the rest of this repository and shares no files or history
with `main`. It holds the code that builds the two daily Instagram posts for @thegildedticker.

- `RUNBOOK.md` — the step-by-step daily procedure. Start here.
- `pipeline/tape.py` — "Ten on the Tape", the 10-slide candlestick carousel.
- `pipeline/reel.py` — the map-explainer Reel (video, cover and an original synthesized soundtrack).
- `pipeline/mkspec.py` — turns story notes plus Robinhood price history into a carousel spec.
- `pipeline/fonts/` — open-licensed fonts (SIL OFL; licence texts alongside). `pipeline/geo/` — country
  outlines from Natural Earth (public domain).
- `specs/` — one JSON per post: the prices, wording and sources behind it. `log/` — what went out each day.

Each day's images and video are pushed to a sibling branch named `gilded-ticker-media-YYYY-MM` so Metricool
can fetch them from a public link. Metricool keeps its own copy, so once a month is over that month's media
branch can be deleted on GitHub to free the space.
