#!/usr/bin/env python3
"""Assemble index.html (public site / Mac) and snapshot.html (Claude artifact) from src/."""
import json, pathlib, re, sys
HERE = pathlib.Path(__file__).resolve().parent
page = (HERE / "src/page.html").read_text()
engine = (HERE / "src/engine.js").read_text()
app = (HERE / "src/app.js").read_text()
assert "/*ENGINE*/" in page and "/*APP*/" in page and "<!--SNAPSHOT-->" in page
out = page.replace("/*ENGINE*/", engine).replace("/*APP*/", app)
(HERE / "index.html").write_text(out.replace("<!--SNAPSHOT-->\n", ""))
snap = json.loads((HERE / "data_snapshot.json").read_text())
(HERE / "snapshot.html").write_text(out.replace("<!--SNAPSHOT-->", "<script>window.__SNAPSHOT__=" + json.dumps(snap, separators=(",", ":")) + ";</script>"))
print("index.html", len(out), "bytes; snapshot.html with", len(snap["symbols"]), "symbols")
