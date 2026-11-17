#!/usr/bin/env python3
"""Fetch your calendar and save the next couple of weeks as data/calendar_window.json.

Usage:
    CALENDAR_ICS_URL=... python3 scripts/calendar_refresh.py     (what the workflow runs)
    python3 scripts/calendar_refresh.py --ics some-feed.ics       (from a file, for testing)

Run by .github/workflows/calendar-refresh.yml, because Claude's cloud sandbox
can't reach calendar hosts (iCloud, Google...) itself. Only the expanded
events from this week's Monday to `calendar.window_days` ahead are written,
never the raw feed, so your full calendar history doesn't end up in git.

The file is rewritten only when its content changes (the window moves once a
day, so at least daily). A feed that suddenly comes back empty while the
previous snapshot had events is treated as a fetch problem: nothing is
overwritten and the exit code is 1, so the workflow run turns red.
"""

import argparse
import os
import sys
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import calendar_status  # noqa: E402
import config  # noqa: E402

MAX_BYTES = 20_000_000


def fetch(url):
    url = url.strip().replace("webcal://", "https://", 1)
    req = urllib.request.Request(url, headers={"User-Agent": "morning-brief-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("feed is larger than 20 MB")
    text = data.decode("utf-8", errors="replace")
    if "BEGIN:VCALENDAR" not in text:
        raise ValueError("the response is not an iCalendar feed (check the link is the private/public ICS one)")
    return text


def build_window(cfg, ics_text, today):
    tz = config.tz(cfg)
    first = today - timedelta(days=today.weekday())
    last = today + timedelta(days=int(config.get(cfg, "calendar.window_days", 14)))
    days, unsupported, warnings = calendar_status.events_between(ics_text, first, last, tz)
    keep_location = config.get(cfg, "calendar.include_locations", True) is True
    slim = {}
    for iso, events in days.items():
        slim[iso] = [{"summary": e["summary"], "location": e["location"] if keep_location else None,
                      "all_day": e["all_day"], "start": e["start"], "end": e["end"]} for e in events]
    return {
        "timezone": str(tz), "first": first.isoformat(), "last": last.isoformat(), "days": slim,
        "unsupported_rrules_skipped": sorted({u.get("summary") or "(untitled)" for u in unsupported}),
        "warnings": sorted(set(warnings))[:20],
    }


def count(window):
    return sum(len(v) for v in (window or {}).get("days", {}).values())


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ics", help="read this .ics file instead of fetching $CALENDAR_ICS_URL")
    args = ap.parse_args()
    cfg = config.load_profile()
    rel = config.get(cfg, "calendar.window_file", "data/calendar_window.json")
    if args.ics:
        with open(args.ics, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        url = os.environ.get("CALENDAR_ICS_URL", "").strip()
        if not url:
            config.log("CALENDAR_ICS_URL is not set (add it under Settings > Secrets and variables > Actions)")
            return 1
        try:
            text = fetch(url)
        except Exception as e:  # noqa: BLE001
            config.log(f"calendar fetch failed: {type(e).__name__}: {e}")  # never print the URL: it's a secret
            return 1
    now = config.now_local(cfg)
    window = build_window(cfg, text, now.date())
    try:
        old = config.read_json(rel, None)
    except ValueError:
        old = None
    if count(window) == 0 and count(old) > 5:
        config.log("the feed has no events in the window but the previous snapshot had some; keeping the old one")
        return 1
    if isinstance(old, dict) and {k: old.get(k) for k in window} == window:
        config.log(f"{rel}: unchanged ({count(window)} events)")
        return 0
    window = dict({"generated_at": now.isoformat(timespec="seconds")}, **window)
    config.write_json(rel, window)
    config.log(f"{rel}: updated ({count(window)} events, {window['first']} to {window['last']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
