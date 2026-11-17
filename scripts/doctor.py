#!/usr/bin/env python3
"""Check your morning-brief setup and say exactly what to fix.

Usage:
    python3 scripts/doctor.py            check config, data files and (if set locally) secrets
    python3 scripts/doctor.py --online   also try the news feeds and look up the repo's visibility
    python3 scripts/doctor.py --ci       for CI: skip checks that need secrets or your own values

Prints OK / WARN / ERROR lines and exits 1 if there is any ERROR. Also prints
the UTC cron line(s) to use for the Claude routine, since routine schedules
are in UTC and don't follow daylight saving time.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

TEMPLATE_DEFAULTS = {"user.name": "Alex", "email.to": "you@example.com"}
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class Report:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def ok(self, msg):
        print(f"  OK     {msg}")

    def warn(self, msg):
        self.warnings += 1
        print(f"  WARN   {msg}")

    def error(self, msg):
        self.errors += 1
        print(f"  ERROR  {msg}")


def check_profile(r, ci):
    try:
        cfg = config.load_profile()
    except config.ConfigError as e:
        r.error(f"config/profile.yaml {e}")
        return None
    except OSError as e:
        r.error(f"config/profile.yaml can't be read ({e})")
        return None
    r.ok("config/profile.yaml parses")
    tzname = config.get(cfg, "user.timezone")
    if not tzname or config.tz(cfg).key != tzname:
        r.error(f"user.timezone {tzname!r} isn't a valid IANA zone (e.g. \"Europe/Berlin\", \"America/New_York\")")
    else:
        r.ok(f"timezone {tzname}")
    for key in ("delivery.time_local", "delivery.backup_after", "delivery.backup_until"):
        v = config.get(cfg, key)
        if v is not None and not HHMM.match(str(v)):
            r.error(f"{key} {v!r} should be \"HH:MM\" (quoted)")
    day = config.weekly_extras_day(cfg)
    if day not in config.WEEKDAYS:
        r.error(f"delivery.weekly_extras_day {day!r} should be a weekday name")
    if not ci:
        for key, default in TEMPLATE_DEFAULTS.items():
            if config.get(cfg, key) == default and (key != "email.to" or config.enabled(cfg, "email")):
                r.warn(f"{key} is still the template's example ({default!r})")
    for i, rot in enumerate(config.as_list(config.get(cfg, "rotations", []))):
        if not isinstance(rot, dict) or not rot.get("name") or not config.as_list(rot.get("items")):
            r.error(f"rotations[{i}] needs a name and at least one item")
    feeds = config.as_list(config.get(cfg, "news.backup_feeds.headlines", [])) + \
        config.as_list(config.get(cfg, "news.backup_feeds.reports", []))
    for line in feeds:
        if not config.split_link(line)[1]:
            r.error(f"news feed {line!r} should look like \"Label | https://...\"")
    return cfg


def check_modules(r, cfg):
    today = config.today_local(cfg)
    if config.enabled(cfg, "countdowns"):
        for it in config.as_list(config.get(cfg, "countdowns.items", [])):
            d = config.to_date(it.get("date")) if isinstance(it, dict) else None
            if not d:
                r.error(f"countdown {it!r} needs a label and a \"YYYY-MM-DD\" date")
            elif d < today:
                r.warn(f"countdown {it.get('label')!r} ({d}) is in the past; remove it or set a new date")
    if config.enabled(cfg, "trips"):
        rel = config.get(cfg, "trips.file", "data/trips.json")
        try:
            data = config.read_json(rel, None)
            if data is None:
                r.error(f"trips is enabled but {rel} doesn't exist")
            else:
                bad = [t.get("name", "?") for t in data.get("trips", [])
                       if not (config.to_date(t.get("start")) and config.to_date(t.get("end")))]
                (r.error(f"{rel}: trips with bad dates: {bad}") if bad else r.ok(f"{rel} parses"))
        except ValueError as e:
            r.error(f"{rel} is not valid JSON ({e})")
    if config.enabled(cfg, "jobs"):
        rel = config.get(cfg, "jobs.csv_file", "data/jobs.csv")
        try:
            with open(config.path(rel), encoding="utf-8-sig", newline="") as f:
                header = [h.strip().lower() for h in next(csv.reader(f), [])]
            missing = [c for c in ("org", "role") if c not in header]
            (r.error(f"{rel} is missing the column(s) {missing}") if missing else r.ok(f"{rel} has the required columns"))
        except OSError:
            r.error(f"jobs is enabled but {rel} doesn't exist")
    rel = config.get(cfg, "day_plan.file", "data/day_plan.json")
    if os.path.exists(config.path(rel)):
        try:
            config.read_json(rel)
            r.ok(f"{rel} parses")
        except ValueError as e:
            r.error(f"{rel} is not valid JSON ({e})")
    if config.enabled(cfg, "calendar"):
        rel = config.get(cfg, "calendar.window_file", "data/calendar_window.json")
        if not os.path.exists(config.path(rel)):
            r.warn(f"calendar is enabled but {rel} doesn't exist yet: run the calendar-refresh workflow once")
    try:
        import facts
        out, _ = facts.build(cfg, today)
        for w in out["warnings"]:
            r.warn(f"facts: {w}")
        r.ok("scripts/facts.py runs")
    except Exception as e:  # noqa: BLE001
        r.error(f"scripts/facts.py failed: {type(e).__name__}: {e}")


def check_secrets(r, cfg):
    need = []
    if config.enabled(cfg, "telegram"):
        need += ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    if config.enabled(cfg, "email"):
        need += ["SMTP_PASSWORD"]
    if config.enabled(cfg, "calendar"):
        need += ["CALENDAR_ICS_URL"]
    if not need:
        r.warn("no delivery channel is enabled: the brief will only be in the routine session and in briefs/")
        return
    print(f"  INFO   repository secrets needed for what you enabled: {', '.join(need)}")
    if os.environ.get("GITHUB_ACTIONS"):
        missing = [n for n in need if not os.environ.get(n)]
        (r.error(f"secrets not set: {missing}") if missing else r.ok("all needed secrets are set"))


def cron_hint(cfg):
    t = str(config.get(cfg, "delivery.time_local", "07:30"))
    if not HHMM.match(t):
        return
    tz = config.tz(cfg)
    year = config.today_local(cfg).year
    lines = {}
    for month in (1, 7):
        local = datetime(year, month, 15, int(t[:2]), int(t[3:]), tzinfo=tz)
        utc = local.astimezone(timezone.utc)
        lines.setdefault(f"{utc.minute} {utc.hour} * * *", []).append("winter" if month == 1 else "summer")
    print(f"\nRoutine schedule for {t} {tz.key} (routine crons are in UTC):")
    for line, seasons in lines.items():
        note = "all year" if len(lines) == 1 else f"{' & '.join(seasons)} time"
        print(f"  cron: {line}   ({note})")
    if len(lines) > 1:
        print("  Your zone has daylight saving time: change the routine's cron when the clocks change,")
        print("  or pick one and accept the brief an hour earlier/later for half the year.")
    start, end = str(config.get(cfg, "delivery.backup_after", "")), str(config.get(cfg, "delivery.backup_until", "18:00"))
    if HHMM.match(start) and HHMM.match(end):
        hours = set()
        for month in (1, 7):
            h = datetime(year, month, 15, int(start[:2]), 0, tzinfo=tz)
            stop = datetime(year, month, 15, int(end[:2]), int(end[3:]), tzinfo=tz)
            while h < stop:
                hours.add(h.astimezone(timezone.utc).hour)
                h += timedelta(hours=1)
        if hours:
            print(f"\nOptional, to save Actions minutes: in .github/workflows/deliver.yml use")
            print(f"  cron: \"17 {','.join(str(x) for x in sorted(hours))} * * *\"   (your backup window in UTC)")


def check_repo(r, online):
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=config.root(), capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return
    if re.search(r"(^|/)\.claude/.*\.lock$", tracked, re.MULTILINE):
        r.warn(".claude/*.lock is tracked by git; run: git rm --cached .claude/*.lock")
    big = [p for p in tracked.splitlines() if os.path.exists(config.path(p)) and os.path.getsize(config.path(p)) > 5_000_000]
    if big:
        r.warn(f"large files are tracked: {big}")
    if online:
        try:
            out = subprocess.run(["gh", "repo", "view", "--json", "visibility"], cwd=config.root(),
                                 capture_output=True, text=True, check=True).stdout
            vis = json.loads(out).get("visibility")
            (r.error("this repo is PUBLIC: your briefs, calendar and state would be published. "
                     "Make it private (Settings > General > Danger Zone).") if vis == "PUBLIC"
             else r.ok(f"repo visibility: {vis.lower()}"))
        except (OSError, subprocess.CalledProcessError, ValueError):
            r.warn("couldn't check the repo's visibility (is the GitHub CLI `gh` installed and logged in?)")


def check_feeds(r, cfg):
    import news_feeds
    for kind in ("headlines", "reports"):
        for line in config.as_list(config.get(cfg, f"news.backup_feeds.{kind}", [])):
            label, url = config.split_link(line)
            if not url:
                continue
            try:
                items = news_feeds.fetch_feed(url)
                dated = [i for i in items if i["when"]]
                recent = [i for i in dated if datetime.now(i["when"].tzinfo) - i["when"] < timedelta(days=7)]
                (r.ok(f"feed {label}: {len(recent)} items from the last week") if recent
                 else r.warn(f"feed {label}: reachable but nothing dated in the last week"))
            except Exception as e:  # noqa: BLE001
                r.warn(f"feed {label} failed: {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--online", action="store_true", help="also test feeds and the repo's visibility")
    ap.add_argument("--ci", action="store_true", help="skip personal-value and secret checks")
    args = ap.parse_args()
    r = Report()
    print("Morning brief doctor\n")
    cfg = check_profile(r, args.ci)
    if cfg is not None:
        check_modules(r, cfg)
        if not args.ci:
            check_secrets(r, cfg)
        if args.online:
            check_feeds(r, cfg)
    check_repo(r, args.online)
    if cfg is not None and not args.ci:
        cron_hint(cfg)
    print(f"\n{r.errors} error(s), {r.warnings} warning(s)")
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
