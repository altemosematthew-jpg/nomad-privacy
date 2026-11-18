"""How many posts can go out today without running out of Metricool's monthly allowance?

Usage:
  python3 pipeline/budget.py D --used N [--cap 20]

  D       today's date in America/Chicago (YYYY-MM-DD)
  --used  posts already created in Metricool this calendar month, any status (PUBLISHED, PENDING, drafts):
          count everything getScheduledPosts returns from the 1st 00:00 to the last day 23:59 of D's month
  --cap   the plan's monthly limit. The owner chose to stay on the Free plan (18 Nov 2026): 20 a month.
          Use --cap 0 if he upgrades (unlimited).

Prints one JSON line, e.g.
  {"post": ["geo"], "default": "geo", "remaining": 10, "weekdays_left": 8, "why": "..."}
"post" lists what to publish today: "finance" (Ten on the Tape Reel, 07:30) and/or "geo" (geopolitics Reel, 10:00).

Rules (so the account posts every trading day instead of going dark at the end of the month):
  - unlimited plan: both Reels every day.
  - nothing left: post nothing.
  - weekend or market holiday: one geopolitics Reel only if there are more posts left than trading days left.
  - trading day: both Reels if at least two are left for every trading day left; otherwise one Reel.
    Default: finance on Tuesday and Thursday, geopolitics on Monday, Wednesday and Friday. RUNBOOK.md says when a
    run may swap the type (a much bigger story on the other side) and caps a type at two days in a row.
"""
import argparse, json, datetime as dt, calendar

# NYSE full-day closures (RUNBOOK.md market calendar)
HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
            "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


def trading_day(d):
    return d.weekday() < 5 and d.isoformat() not in HOLIDAYS


def plan(day, used, cap=20):
    d = dt.date.fromisoformat(day)
    last = dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    left = [d + dt.timedelta(days=i) for i in range((last - d).days + 1)]
    weekdays_left = sum(trading_day(x) for x in left)
    default = "finance" if d.weekday() in (1, 3) else "geo"
    if cap == 0:
        return {"post": ["finance", "geo"], "default": default, "remaining": None, "weekdays_left": weekdays_left,
                "why": "unlimited plan: both Reels"}
    remaining = cap - used
    base = {"default": default, "remaining": remaining, "weekdays_left": weekdays_left}
    if remaining <= 0:
        return {"post": [], **base, "why": f"monthly cap of {cap} reached ({used} used)"}
    if not trading_day(d):
        if remaining > weekdays_left:
            return {"post": ["geo"], **base, "why": f"spare posts ({remaining} left for {weekdays_left} trading days): one geopolitics Reel"}
        return {"post": [], **base, "why": f"no spare posts ({remaining} left for {weekdays_left} trading days): rest day"}
    if remaining >= 2 * weekdays_left:
        return {"post": ["finance", "geo"], **base, "why": f"{remaining} left for {weekdays_left} trading days: both Reels"}
    return {"post": [default], **base, "why": f"{remaining} left for {weekdays_left} trading days: one Reel ({default} by default)"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("day")
    ap.add_argument("--used", type=int, required=True)
    ap.add_argument("--cap", type=int, default=20)
    a = ap.parse_args()
    print(json.dumps(plan(a.day, a.used, a.cap)))
