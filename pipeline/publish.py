"""Host a day's media and write the exact Metricool requests, so the scheduling step is copy-and-call.

Usage (from the repo root, after the posts are rendered and checked):
  python3 pipeline/publish.py D [--finance out/D/finance] [--reel out/D/reel] [--media ../media]
                              [--finance-time 07:30] [--reel-time 10:00]
                              [--finance-first-comment "..."] [--first-comment "PEACE or PAUSE? One word. Then tell me why."]
                              [--trailer "Co-Authored-By: ..."] [--dry-run]
  Each post is included when its folder exists (out/D/finance, out/D/reel, and the old carousel out/D/tape);
  pass --finance none / --reel none / --tape none to leave one out. Captions: out/D/finance_caption.txt,
  out/D/reel_caption.txt, out/D/tape_caption.txt.

What it does
  1. Makes sure ../media is a clone of branch gilded-ticker-media-YYYY-MM (clones it, or starts the
     branch if the month is new). Plain pushes only; nothing is ever overwritten: every file is stored
     under a name that includes a hash of its content (01-3f9c2a1b7e.jpg), so a corrected slide simply
     gets a new name and a new link.
  2. Copies each post's files (finance: reel.mp4 + cover.jpg, reel: reel.mp4 + cover.jpg, tape: 10 slides)
     into D/finance, D/reel, D/tape, commits, pushes.
  3. Waits until every public link answers 200 with the right size.
  4. Writes out/D/metricool_finance.json, out/D/metricool_reel.json (and metricool_tape.json for a carousel):
       {"blogId": "7018528", "date": "...", "info": "<JSON string>"}
     Pass the three fields as they are to createScheduledPost.
Skip a post with --tape none or --reel none.
"""
import argparse, json, os, shutil, subprocess, sys, time, hashlib, datetime as dt
from zoneinfo import ZoneInfo

REPO = "https://github.com/altemosematthew-jpg/nomad-privacy"
RAW = "https://raw.githubusercontent.com/altemosematthew-jpg/nomad-privacy"
BLOG = "7018528"
TZ = "America/Chicago"
DEFAULT_TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}\n{r.stdout}\n{r.stderr}")
    return r


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def ensure_media_clone(path, branch):
    if os.path.isdir(os.path.join(path, ".git")):
        cur = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path).stdout.strip()
        if cur != branch:
            raise SystemExit(f"{path} is on branch {cur}, expected {branch}")
        run(["git", "pull", "--ff-only", "origin", branch], cwd=path, check=False)
        return
    exists = run(["git", "ls-remote", "--heads", REPO, branch]).stdout.strip()
    if exists:
        run(["git", "clone", "--depth", "1", "--branch", branch, REPO, path])
    else:
        os.makedirs(path, exist_ok=True)
        run(["git", "init", "-q", "-b", branch], cwd=path)
        run(["git", "remote", "add", "origin", REPO], cwd=path)
        ym = branch.rsplit("-", 2)[-2:]
        open(os.path.join(path, "README.md"), "w").write(
            f"# The Gilded Ticker — media ({'-'.join(ym)})\n\nInstagram images and videos for @thegildedticker, hosted here so Metricool can "
            "fetch them from a public link. Metricool keeps its own copy, so this branch can be deleted once the month is over. "
            "It shares nothing with `main`.\n")


def place(src, dst_dir, name):
    """Copy src into dst_dir as <stem>-<content hash><ext>. A name always means one exact file, so a link
    can never serve stale content from the public host's cache, and re-running is harmless."""
    os.makedirs(dst_dir, exist_ok=True)
    stem, ext = os.path.splitext(name)
    final = f"{stem}-{sha(src)[:10]}{ext}"
    dst = os.path.join(dst_dir, final)
    if not os.path.exists(dst):
        shutil.copyfile(src, dst)
    return final


def wait_public(urls_sizes, timeout=240):
    t0 = time.time()
    pending = dict(urls_sizes)
    while pending and time.time() - t0 < timeout:
        for url, size in list(pending.items()):
            r = run(["curl", "-sSI", "-m", "30", url], check=False)
            ok = any(l.startswith("HTTP/2 200") or l.startswith("HTTP/1.1 200") for l in r.stdout.splitlines())
            length = [l.split(":", 1)[1].strip() for l in r.stdout.splitlines() if l.lower().startswith("content-length")]
            if ok and length and int(length[-1]) == size:
                del pending[url]
        if pending:
            time.sleep(8)
    if pending:
        raise SystemExit("these links never came up:\n  " + "\n  ".join(pending))


def iso_with_offset(day, hhmm):
    t = dt.datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(TZ))
    return t.isoformat(), t.strftime("%Y-%m-%dT%H:%M:%S")


def reel_info(cap, base, files, local, first_comment):
    mp4, cover = files
    return {"autoPublish": True, "descendants": [], "draft": False, "firstCommentText": first_comment, "hasNotReadNotes": False,
            "media": [f"{base}/{mp4}"], "videoThumbnailUrl": f"{base}/{cover}", "mediaAltText": [],
            "providers": [{"network": "instagram"}], "publicationDate": {"dateTime": local, "timezone": TZ},
            "shortener": False, "smartLinkData": {"ids": []}, "text": cap,
            "instagramData": {"type": "REEL", "showReelOnFeed": True, "isAiGenerated": False}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--finance", default=None, help="finance Reel folder (default out/D/finance if it exists)")
    ap.add_argument("--reel", default=None, help="geopolitics Reel folder (default out/D/reel if it exists)")
    ap.add_argument("--tape", default=None, help="old 10-slide carousel folder (default out/D/tape if it exists)")
    ap.add_argument("--media", default="../media")
    ap.add_argument("--finance-time", default="07:30")
    ap.add_argument("--reel-time", default="10:00")
    ap.add_argument("--tape-time", default="07:30")
    ap.add_argument("--finance-caption", default=None)
    ap.add_argument("--reel-caption", default=None)
    ap.add_argument("--tape-caption", default=None)
    ap.add_argument("--tape-spec", default=None)
    ap.add_argument("--finance-first-comment", default="")
    ap.add_argument("--first-comment", default="", help="first comment on the geopolitics Reel")
    ap.add_argument("--dry-run", action="store_true", help="copy into the clone and print, but do not commit, push or wait")
    ap.add_argument("--trailer", action="append", default=None,
                    help="a line to end the media commit message with (repeat for several); default: " + DEFAULT_TRAILER)
    a = ap.parse_args()
    D = a.day
    out = f"out/{D}"

    def pick(val, name):
        if val == "none":
            return None
        if val:
            return val
        return f"{out}/{name}" if os.path.isdir(f"{out}/{name}") else None

    fin_dir, reel_dir, tape_dir = pick(a.finance, "finance"), pick(a.reel, "reel"), pick(a.tape, "tape")
    if not (fin_dir or reel_dir or tape_dir):
        raise SystemExit("nothing to publish: no out/D/finance, out/D/reel or out/D/tape")
    branch = f"gilded-ticker-media-{D[:7]}"
    media = os.path.abspath(a.media)
    ensure_media_clone(media, branch)

    hosted = {}
    for key, folder in (("finance", fin_dir), ("reel", reel_dir)):
        if folder:
            for f in ("reel.mp4", "cover.jpg"):
                if not os.path.exists(os.path.join(folder, f)):
                    raise SystemExit(f"missing {folder}/{f}")
            hosted[key] = [place(os.path.join(folder, f), os.path.join(media, D, key), f) for f in ("reel.mp4", "cover.jpg")]
    if tape_dir:
        slides = [os.path.join(tape_dir, f"{i:02d}.jpg") for i in range(1, 11)]
        missing = [x for x in slides if not os.path.exists(x)]
        if missing:
            raise SystemExit(f"missing slides: {missing}")
        hosted["tape"] = [place(x, os.path.join(media, D, "tape"), os.path.basename(x)) for x in slides]
    if a.dry_run:
        print("DRY RUN - would host:", json.dumps(hosted, indent=1))
        print(run(["git", "status", "--short"], cwd=media).stdout)
        return
    run(["git", "add", "-A"], cwd=media)
    if run(["git", "status", "--porcelain"], cwd=media).stdout.strip():
        trailer = "\n".join(a.trailer or [DEFAULT_TRAILER])
        run(["git", "commit", "-q", "-m", f"Media for {D}\n\n{trailer}"], cwd=media)
        r = run(["git", "push", "origin", f"HEAD:{branch}"], cwd=media, check=False)
        if r.returncode != 0:
            raise SystemExit("push refused:\n" + r.stderr)
    base = f"{RAW}/{branch}/{D}"
    checks = {}
    for key, names in hosted.items():
        for n in names:
            checks[f"{base}/{key}/{n}"] = os.path.getsize(os.path.join(media, D, key, n))
    wait_public(checks)
    print(f"hosted and public: {len(checks)} files on {branch}")

    if fin_dir:
        cap = open(a.finance_caption or f"{out}/finance_caption.txt").read().strip()
        date_iso, local = iso_with_offset(D, a.finance_time)
        info = reel_info(cap, f"{base}/finance", hosted["finance"], local, a.finance_first_comment)
        json.dump({"blogId": BLOG, "date": date_iso, "info": json.dumps(info, ensure_ascii=False)},
                  open(f"{out}/metricool_finance.json", "w"), ensure_ascii=False, indent=1)
        print("wrote", f"{out}/metricool_finance.json")
    if reel_dir:
        cap = open(a.reel_caption or f"{out}/reel_caption.txt").read().strip()
        date_iso, local = iso_with_offset(D, a.reel_time)
        info = reel_info(cap, f"{base}/reel", hosted["reel"], local, a.first_comment)
        json.dump({"blogId": BLOG, "date": date_iso, "info": json.dumps(info, ensure_ascii=False)},
                  open(f"{out}/metricool_reel.json", "w"), ensure_ascii=False, indent=1)
        print("wrote", f"{out}/metricool_reel.json")
    if tape_dir:
        cap = open(a.tape_caption or f"{out}/tape_caption.txt").read().strip()
        spec_p = a.tape_spec or f"specs/{D}-tape.json"
        alt = []
        if os.path.exists(spec_p):
            spec = json.load(open(spec_p))
            when = spec.get("move_label", spec.get("session_day", ""))
            for i, s in enumerate(spec["stocks"]):
                p = (s["close"] / s["prev_close"] - 1) * 100
                verb = "rose" if p >= 0 else "fell"
                head_ = "Ten on the Tape, slide 1: " if i == 0 else f"Slide {i + 1}: "
                alt.append(f"{head_}{s['name']} {verb} {abs(p):.1f} percent ({when}). Candlestick chart of the last two months.")
        date_iso, local = iso_with_offset(D, a.tape_time)
        info = {"autoPublish": True, "descendants": [], "draft": False, "firstCommentText": "", "hasNotReadNotes": False,
                "media": [f"{base}/tape/{n}" for n in hosted["tape"]], "mediaAltText": alt,
                "providers": [{"network": "instagram"}], "publicationDate": {"dateTime": local, "timezone": TZ},
                "shortener": False, "smartLinkData": {"ids": []}, "text": cap,
                "instagramData": {"type": "POST", "showReelOnFeed": True, "isAiGenerated": False}}
        json.dump({"blogId": BLOG, "date": date_iso, "info": json.dumps(info, ensure_ascii=False)},
                  open(f"{out}/metricool_tape.json", "w"), ensure_ascii=False, indent=1)
        print("wrote", f"{out}/metricool_tape.json")


if __name__ == "__main__":
    main()
