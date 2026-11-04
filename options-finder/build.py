#!/usr/bin/env python3
"""Assemble index.html (public site / Mac) and snapshot.html (Claude artifact) from src/."""
import json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
page = (HERE / "src/page.html").read_text()
engine = (HERE / "src/engine.js").read_text()
app = (HERE / "src/app.js").read_text()
assert "/*ENGINE*/" in page and "/*APP*/" in page and "<!--SNAPSHOT-->" in page
mobile = (HERE / "src/mobile.css").read_text() if (HERE / "src/mobile.css").exists() else ""
if mobile.strip():   # phone / narrow-width rules, appended to the end of the page's main style block
    i = page.index("</style>"); page = page[:i] + "\n/* ---- src/mobile.css ---- */\n" + mobile + "\n" + page[i:]
out = page.replace("/*ENGINE*/", engine).replace("/*APP*/", app)
(HERE / "index.html").write_text('<!doctype html>\n<meta charset="utf-8">\n' + out.replace("<!--SNAPSHOT-->\n", ""))
snap = json.loads((HERE / "data_snapshot.json").read_text())
(HERE / "snapshot.html").write_text(out.replace("<!--SNAPSHOT-->", "<script>window.__SNAPSHOT__=" + json.dumps(snap, separators=(",", ":")) + ";</script>"))
print("index.html", len(out), "bytes; snapshot.html with", len(snap["symbols"]), "symbols")
