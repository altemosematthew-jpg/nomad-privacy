# The Gilded Ticker — Instagram pipeline

This branch (`gilded-ticker`) is separate from the rest of this repository. It holds the code that
builds the daily Instagram post for @thegildedticker. It shares no files or history with `main`.

- `RUNBOOK.md` — the step-by-step daily procedure.
- `pipeline/` — design kit, fonts and slide renderers.
- `specs/` — one JSON file per day: the prices, sources and wording behind that day's post.

The images themselves are pushed to the sibling branch `gilded-ticker-media`, which only ever holds the
most recent days, so that Metricool can fetch them from a public link.
