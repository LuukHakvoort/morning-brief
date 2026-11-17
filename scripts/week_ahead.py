"""Calendar access, weekly fixed items, and the 7-day overview (used by facts.py).

The calendar comes from data/calendar_window.json (calendar.window_file),
which .github/workflows/calendar-refresh.yml writes from your private ICS
link: Claude's cloud sandbox can't fetch calendar hosts itself. Events whose
title contains one of `calendar.hide_patterns` are left out everywhere.

Weekly fixed items (profile.yaml `weekly_fixed_items`):
    - name: "Football practice"
      day: "Wednesday"            # a weekday name, "Wednesday evening", or "flexible"
      time: "19:00-20:30"         # optional
      note: "bring the key"       # optional
      away_ok: false              # true = still happens when you're away (e.g. an online class)
"""

import re
from datetime import datetime, timedelta

import config

WEEKDAYS = config.WEEKDAYS
SHORT_MONTHS = [m[:3] for m in config.MONTHS]


def short(d):
    return f"{SHORT_MONTHS[d.month - 1]} {d.day}"


def hm(text, default="17:00"):
    for value in (text, default):
        try:
            return datetime.strptime(str(value).strip()[:5], "%H:%M").time()
        except (TypeError, ValueError):
            continue
    return datetime.strptime("17:00", "%H:%M").time()


def ev_times(ev):
    try:
        return datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"] or ev["start"])
    except (KeyError, TypeError, ValueError):
        return None, None


def fixed_items(cfg):
    out = []
    for it in config.as_list(config.get(cfg, "weekly_fixed_items", [])):
        if isinstance(it, dict) and it.get("name"):
            out.append({"name": str(it["name"]), "day": str(it.get("day") or ""), "time": str(it.get("time") or ""),
                        "note": str(it.get("note") or ""), "away_ok": it.get("away_ok") is True})
    return out


class Calendar:
    """Events per local day from the committed calendar window."""

    def __init__(self, cfg, today, warnings):
        self.enabled = config.enabled(cfg, "calendar")
        self.days, self.generated_at, self.first, self.last = {}, None, None, None
        self.hide = [str(p).lower() for p in config.as_list(config.get(cfg, "calendar.hide_patterns", [])) if p]
        self.home_only = [str(p).lower() for p in config.as_list(config.get(cfg, "calendar.home_only_patterns", [])) if p]
        self.fixed_names = [f["name"].lower() for f in fixed_items(cfg) if not f["away_ok"] and len(f["name"]) > 3]
        self.warnings = warnings
        self.available = False
        if not self.enabled:
            return
        rel = config.get(cfg, "calendar.window_file", "data/calendar_window.json")
        try:
            data = config.read_json(rel, None)
        except ValueError as e:
            warnings.append(f"{rel} is not valid JSON ({e})")
            return
        if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
            warnings.append(f"calendar is enabled but {rel} doesn't exist yet: run the calendar-refresh workflow once")
            return
        self.available = True
        self.days = data["days"]
        self.first, self.last = config.to_date(data.get("first")), config.to_date(data.get("last"))
        self.generated_at = data.get("generated_at")
        stale_after = int(config.get(cfg, "calendar.stale_after_days", 2))
        try:
            age = (datetime.now(config.tz(cfg)) - datetime.fromisoformat(self.generated_at)).days
        except (TypeError, ValueError):
            age = None
        if age is not None and age > stale_after:
            warnings.append(f"the calendar snapshot is {age} days old: the calendar-refresh workflow may be failing")
        if self.last and today > self.last:
            warnings.append("today is past the end of the calendar snapshot: the calendar-refresh workflow may be failing")

    def events(self, d, away=False):
        """Events on d, minus hidden ones (and home-only ones while away)."""
        out = []
        for ev in self.days.get(d.isoformat(), []):
            low = (ev.get("summary") or "").lower()
            if any(p in low for p in self.hide):
                continue
            if away and (any(p in low for p in self.home_only) or any(n in low for n in self.fixed_names)):
                continue
            out.append(ev)
        return out


def event_label(ev):
    s, _ = ev_times(ev)
    name = ev.get("summary") or "(untitled)"
    return name if ev.get("all_day") or s is None else f"{s:%H:%M} {name}"


def fixed_for(ctx, d):
    """(today's fixed items, ones skipped because you're away) for date d."""
    wd = WEEKDAYS[d.weekday()].lower()
    _, _, away = ctx["where"](d)
    todays = [f for f in ctx["fixed"] if re.search(rf"\b{wd}\b", f["day"].lower())]
    if not away:
        return todays, []
    return [f for f in todays if f["away_ok"]], [f for f in todays if not f["away_ok"]]


def build_days(ctx):
    """Today + the next 6 days at a glance."""
    results = ctx["results"]
    runs = ((results.get("workout") or {}).get("runs") or {}).get("plan") or []
    run_dates = {r["date"]: r["type"] for r in runs}
    countdown_dates = {}
    for c in (results.get("countdowns") or {}).get("upcoming", []):
        countdown_dates.setdefault(c["date"], []).append(c["label"])
    days = []
    for i in range(7):
        d = ctx["today"] + timedelta(days=i)
        loc, trip, away = ctx["where"](d)
        todays, skipped = fixed_for(ctx, d)
        days.append({
            "date": d.isoformat(), "weekday": WEEKDAYS[d.weekday()], "location": loc, "away": away,
            "travel": d in ctx["travel_days"],
            "sessions": [f"{s.get('when', '')} {s.get('title', '')}".strip()
                         for s in (trip or {}).get("sessions", []) if s.get("date") == d.isoformat()],
            "events": [event_label(ev) for ev in ctx["cal"].events(d, away=away)],
            "fixed_items": [f["name"] for f in todays],
            "skipped_while_away": [f["name"] for f in skipped],
            "countdowns": countdown_dates.get(d.isoformat(), []),
            "run": run_dates.get(d.isoformat()),
        })
    return days

