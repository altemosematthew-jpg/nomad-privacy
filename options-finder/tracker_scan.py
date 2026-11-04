#!/usr/bin/env python3
"""Today's chains for the track-record job: straight from Cboe, else from the public Strike Finder server.
Usage: python3 tracker_scan.py OUT.json"""
import json
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import finder  # noqa: E402

out_path = sys.argv[1]
data = None
try:
    data = finder.scan()
    if len(data.get("symbols") or []) < 5:
        raise RuntimeError("only %d symbols: %s" % (len(data.get("symbols") or []), data.get("errors")))
    print("direct Cboe scan: %d symbols" % len(data["symbols"]))
except Exception as e:  # noqa: BLE001
    print("direct Cboe scan failed (%s); asking the public server" % e, file=sys.stderr)
    req = urllib.request.Request("https://strike-finder.onrender.com/api/scan", headers={"User-Agent": "strike-finder-tracker"})
    for attempt in range(4):
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=150).read().decode("utf-8"))
            if data.get("symbols"):
                print("server scan: %d symbols" % len(data["symbols"]))
                break
        except Exception as e2:  # noqa: BLE001
            print("server attempt %d failed: %s" % (attempt + 1, e2), file=sys.stderr)
        time.sleep(25)
if not data or not data.get("symbols"):
    sys.exit("no data from Cboe or the server")
pathlib.Path(out_path).write_text(json.dumps(data))
