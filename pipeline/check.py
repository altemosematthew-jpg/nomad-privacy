"""Last check before scheduling: the files, the captions and the numbers agree with each other.

Usage (from the repo root):
  python3 pipeline/check.py D            # checks out/D/tape, out/D/reel, the captions and specs/D-*.json
Exit code 1 if anything is wrong; every problem is printed with "!!".

Checks
  carousel  10 JPEGs, each 1080x1350
            caption: <= 2,200 characters, exactly 5 hashtags, the 10 numbered lines match the spec's tickers,
            order and moves (one decimal), "closing prices" names the session day, the not-advice line is there
  reel      reel.mp4 is H.264 1080x1920 at 30 fps with AAC audio, 45-62 s long; cover.jpg is 1080x1920
            caption: <= 2,200 characters, exactly 5 hashtags, has "Watch to the end", a "Comment X or Y" question,
            "Sources:", the not-advice line, and no leftover instructions such as "PINNED COMMENT"
  both      no unbalanced brackets, no "TODO", no template words left in, straight text (no markdown)
"""
import json, os, re, subprocess, sys
from PIL import Image

problems = []


def bad(msg):
    problems.append(msg)
    print("  !! " + msg)


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


def ffprobe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
                        "-of", "json", path], capture_output=True, text=True)
    return json.loads(r.stdout or "{}")


def main(D):
    out = f"out/{D}"
    print(f"CHECK {D}")
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
        mp4 = f"{reel_dir}/reel.mp4"
        if not os.path.exists(mp4):
            bad(f"missing {mp4}")
        else:
            info = ffprobe(mp4)
            v = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
            au = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
            dur = float(info.get("format", {}).get("duration", 0))
            if not v or v[0].get("codec_name") != "h264" or (v[0].get("width"), v[0].get("height")) != (1080, 1920) or v[0].get("r_frame_rate") != "30/1":
                bad(f"reel.mp4 video is {v[0] if v else 'missing'}; need H.264 1080x1920 30 fps")
            if not au or au[0].get("codec_name") != "aac":
                bad("reel.mp4 needs an AAC audio track")
            if not 45 <= dur <= 62:
                bad(f"reel.mp4 is {dur:.1f} s; aim for 45-62 s")
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
            if "Watch to the end" not in text:
                bad("reel caption: missing 'Watch to the end.'")
            if not re.search(r"Comment [A-Z][A-Z' ]* or [A-Z][A-Z' ]*", text):
                bad("reel caption: missing the one-word question ('Comment PEACE or PAUSE.')")
            first = text.split("\n")[0]
            if "|" not in first:
                bad("reel caption: first line should be 'Title | subtitle'")
        sb_p = f"specs/{D}-reel.json"
        if os.path.exists(sb_p):
            sb = json.load(open(sb_p))
            missing_src = [i + 1 for i, s in enumerate(sb["scenes"]) if not s.get("src")]
            if missing_src:
                bad(f"reel storyboard: scenes {missing_src} have no source line")
        else:
            bad(f"missing {sb_p}")
        if len(problems) == n0:
            print("  ok")
    print("ALL CHECKS PASSED" if not problems else f"{len(problems)} PROBLEM(S) - fix before scheduling")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main(sys.argv[1])
