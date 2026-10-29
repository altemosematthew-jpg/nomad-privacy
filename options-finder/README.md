# Options Finder (Mac mini)

Local scanner for US stock options. Free Cboe delayed quotes (15 min), no API keys, no Claude usage.

- **Start:** double-click `Start Options Finder.command` (installs a launchd service that starts at login and restarts if it crashes), then open http://127.0.0.1:8765
- **Stop:** `Stop Options Finder.command`
- **Watchlist:** edit `watchlist.json` (a JSON list of symbols) — or type any symbol into the page's "Add" box.
- **Shareable snapshot:** the published Claude artifact carries a frozen snapshot; the local page is live.
- Nothing here places orders. The page deep-links into Robinhood's chain for the symbol and gives you the exact contract to enter.
