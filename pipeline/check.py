"""Last check before scheduling: the files, the captions and the numbers agree with each other.

Usage (from the repo root):
  python3 pipeline/check.py D            # checks out/D/tape, out/D/reel, the captions and specs/D-*.json
Exit code 1 if anything is wrong; every problem is printed with "!!".

Checks
  finance   out/D/finance/reel.mp4 is H.264 1080x1920 30 fps with AAC audio, 25-45 s; cover.jpg 1080x1920;
            out/D/finance_caption.txt: the 10 "$SYM +x.x%" lines match the spec's tickers, order and moves (one decimal),
            the session day is named, sources and the not-advice line are there
  carousel  (old format, only if out/D/tape exists) 10 JPEGs, each 1080x1350
            caption: <= 2,200 characters, exactly 5 hashtags, the 10 numbered lines match the spec's tickers,
            order and moves (one decimal), "closing prices" names the session day, the not-advice line is there
  reel      reel.mp4 is H.264 1080x1920 at 30 fps with AAC audio, 45-62 s long; cover.jpg is 1080x1920
            caption: <= 2,200 characters, exactly 5 hashtags, a "Comment X or Y" question,
            "Sources:", the not-advice line, and no leftover instructions such as "PINNED COMMENT"
  voice     captions and on-screen text avoid the phrases that make posts read as machine-written
            (AI_TELLS below: "Watch to the end", "Here's why", em dashes, ...)
  both      no unbalanced brackets, no "TODO", no template words left in, straight text (no markdown)
"""
import json, os, re, subprocess, sys
from PIL import Image

problems = []


def bad(msg):
    problems.append(msg)
    print("  !! " + msg)


AI_TELLS = ["watch to the end", "watch till the end", "here's why", "here's what", "here's how", "let's dive", "dive in",
            "delve", "game-changer", "game changer", "buckle up", "in a world where", "stay tuned", "it's not just",
            "the stakes", "unpack", "\u2014", "!!", "\U0001F680", "\U0001F525"]


def voice_check(name, text):
    low = text.lower()
    for t in AI_TELLS:
        if t in low:
            shown = {"\u2014": "an em dash", "\U0001F680": "the rocket emoji", "\U0001F525": "the fire emoji"}.get(t, repr(t))
            bad(f"{name}: contains {shown}, which reads as machine-written; say it plainly")


def video_checks(label, mp4, lo, hi):
    if not os.path.exists(mp4):
        bad(f"missing {mp4}")
        return
    info = ffprobe(mp4)
    v = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    au = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    dur = float(info.get("format", {}).get("duration", 0))
    if not v or v[0].get("codec_name") != "h264" or (v[0].get("width"), v[0].get("height")) != (1080, 1920) or v[0].get("r_frame_rate") != "30/1":
        bad(f"{label} video is {v[0] if v else 'missing'}; need H.264 1080x1920 30 fps")
    if not au or au[0].get("codec_name") != "aac":
        bad(f"{label} needs an AAC audio track")
    if not lo <= dur <= hi:
        bad(f"{label} is {dur:.1f} s; aim for {lo}-{hi} s")
    if os.path.getsize(mp4) > 45 * 1024 * 1024:
        bad(f"{label} is {os.path.getsize(mp4) // 1048576} MB; keep it under 45 MB for the public host")


def common_caption_checks(name, text):
    if len(text) > 2200:
        bad(f"{name}: {len(text)} characters (Instagram allows 2,200)")
    tags = re.findall(r"(?<!\w)#\w+", text)
    if len(tags) != 5:
        bad(f"{name}: {len(tags)} hashtags, the account uses exactly 5")
    if len(set(t.lower() for t in tags)) != len(tags):
        bad(f"{name}: repeated hashtag")
    if not text.rstrip().split("\n")[-1].strip().startswith("#"):
        bad(f"{name}: the hashtags should be the last line")
    for bad_word in ("PINNED COMMENT", "TODO", "TBD", "XXX", "lorem", "<", ">", "**", "__", "{", "}"):
        if bad_word.lower() in text.lower():
            bad(f"{name}: contains '{bad_word}'")
    if text.count("(") != text.count(")") or text.count("[") != text.count("]"):
        bad(f"{name}: unbalanced brackets")
    if "not financial advice" not in text.lower() and "not investment advice" not in text.lower():
        bad(f"{name}: missing the not-advice line")
    if "Sources:" not in text and "Source:" not in text:
        bad(f"{name}: missing sources")
    voice_check(name, text)


def ffprobe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def main(D):
    out = f"out/{D}"
    print(f"CHECK {D}")
    # ---------- finance Reel ----------
    fin_dir, spec_p = f"{out}/finance", f"specs/{D}-tape.json"
    if os.path.isdir(fin_dir):
        n0 = len(problems)
        print("finance reel")
        video_checks("finance reel.mp4", f"{fin_dir}/reel.mp4", 25, 45)
        cov = f"{fin_dir}/cover.jpg"
        if not os.path.exists(cov):
            bad(f"missing {cov}")
        elif Image.open(cov).size != (1080, 1920):
            bad(f"finance cover.jpg is {Image.open(cov).size}, need 1080x1920")
        cap_p = f"{out}/finance_caption.txt"
        if not os.path.exists(cap_p):
            bad(f"missing {cap_p}")
        elif not os.path.exists(spec_p):
            bad(f"missing {spec_p}")
        else:
            text = open(cap_p).read().strip()
            spec = json.load(open(spec_p))
            common_caption_checks("finance caption", text)
            lines = re.findall(r"^\$([A-Z.]+) ([+−-])(\d+\.\d)%", text, flags=re.M)
            if len(lines) != 10:
                bad(f"finance caption: found {len(lines)} '$SYM +x.x%' lines, need 10 (one per stock, in Reel order)")
            for n, ((sym, sign, val), s) in enumerate(zip(lines, spec["stocks"]), 1):
                p = (s["close"] / s["prev_close"] - 1) * 100
                want_sign = "+" if p >= 0 else "−"
                if sym != s["sym"]:
                    bad(f"finance caption line {n}: ${sym}, but stock {n} in the Reel is ${s['sym']}")
                if f"{abs(p):.1f}" != val or (sign != want_sign and not (sign == "-" and want_sign == "−")):
                    bad(f"finance caption line {n}: {sign}{val}%, but the Reel shows {want_sign}{abs(p):.1f}%")
                if sign == "-":
                    bad(f"finance caption line {n}: use the real minus sign −, not a hyphen")
            day = spec.get("session_day", "")
            if day and day not in text:
                bad(f"finance caption: never names the session day ({day})")
            for ix in spec.get("indices", []):
                p = (ix["close"] / ix["prev_close"] - 1) * 100
                want = ("+" if p >= 0 else "−") + f"{abs(p):.1f}%"
                if ix["name"] in text and want not in text:
                    bad(f"finance caption: {ix['name']} should read {want}")
            for k in ("reel_hook", "reel_sub", "reel_outro"):
                if spec.get(k):
                    voice_check(f"finance {k}", spec[k])
        if len(problems) == n0:
            print("  ok")
    # ---------- carousel ----------
    tape_dir, spec_p = f"{out}/tape", f"specs/{D}-tape.json"
    if os.path.isdir(tape_dir):
        print("carousel")
        for i in range(1, 11):
            p = f"{tape_dir}/{i:02d}.jpg"
            if not os.path.exists(p):
                bad(f"missing {p}")
                continue
            im = Image.open(p)
            if im.size != (1080, 1350) or im.format != "JPEG":
                bad(f"{p}: {im.format} {im.size}, need JPEG 1080x1350")
        cap_p = f"{out}/tape_caption.txt"
        if not os.path.exists(cap_p):
            bad(f"missing {cap_p}")
        elif not os.path.exists(spec_p):
            bad(f"missing {spec_p}")
        else:
            text = open(cap_p).read().strip()
            spec = json.load(open(spec_p))
            common_caption_checks("carousel caption", text)
            lines = re.findall(r"^(\d+)\. \$([A-Z.]+) ([+−-])(\d+\.\d)%", text, flags=re.M)
            if len(lines) != 10:
                bad(f"carousel caption: found {len(lines)} numbered '$SYM +x.x%' lines, need 10")
            for (n, sym, sign, val), s in zip(lines, spec["stocks"]):
                p = (s["close"] / s["prev_close"] - 1) * 100
                want_sign = "+" if p >= 0 else "−"
                if sym != s["sym"]:
                    bad(f"carousel caption line {n}: ${sym}, but slide {n} is ${s['sym']}")
                if f"{abs(p):.1f}" != val or (sign != want_sign and not (sign == "-" and want_sign == "−")):
                    bad(f"carousel caption line {n}: {sign}{val}%, but the slide shows {want_sign}{abs(p):.1f}%")
                if sign == "-":
                    bad(f"carousel caption line {n}: use the real minus sign −, not a hyphen")
            day = spec.get("session_day", "")
            if day and day not in text:
                bad(f"carousel caption: never names the session day ({day})")
            for ix in spec.get("indices", []):
                p = (ix["close"] / ix["prev_close"] - 1) * 100
                want = ("+" if p >= 0 else "−") + f"{abs(p):.1f}%"
                if ix["name"] in text and want not in text:
                    bad(f"carousel caption: {ix['name']} should read {want}")
        print("  ok" if not problems else "")
    # ---------- reel ----------
    reel_dir = f"{out}/reel"
    if os.path.isdir(reel_dir):
        n0 = len(problems)
        print("reel")
        video_checks("reel.mp4", f"{reel_dir}/reel.mp4", 45, 62)
        cov = f"{reel_dir}/cover.jpg"
        if not os.path.exists(cov):
            bad(f"missing {cov}")
        elif Image.open(cov).size != (1080, 1920):
            bad(f"cover.jpg is {Image.open(cov).size}, need 1080x1920")
        cap_p = f"{out}/reel_caption.txt"
        if not os.path.exists(cap_p):
            bad(f"missing {cap_p}")
        else:
            text = open(cap_p).read().strip()
            common_caption_checks("reel caption", text)
            if not re.search(r"Comment [A-Z][A-Z' ]* or [A-Z][A-Z' ]*", text):
                bad("reel caption: missing the one-word question ('Comment PEACE or PAUSE.')")
            if len(text) > 1300:
                bad(f"reel caption: {len(text)} characters; keep it under about 1,300 (short reads as human)")
        sb_p = f"specs/{D}-reel.json"
        if os.path.exists(sb_p):
            sb = json.load(open(sb_p))
            missing_src = [i + 1 for i, s in enumerate(sb["scenes"]) if not s.get("src")]
            if missing_src:
                bad(f"reel storyboard: scenes {missing_src} have no source line")
            for i, sc in enumerate(sb["scenes"]):
                for k in ("headline", "sub"):
                    if sc.get(k):
                        voice_check(f"reel scene {i + 1} {k}", sc[k])
        else:
            bad(f"missing {sb_p}")
        if len(problems) == n0:
            print("  ok")
    print("ALL CHECKS PASSED" if not problems else f"{len(problems)} PROBLEM(S) - fix before scheduling")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main(sys.argv[1])
