"""Trips: where you are each day, today's trip agenda, and prep/follow-up tasks.

profile.yaml:
    trips:
      enabled: true
      file: "data/trips.json"

data/trips.json (dates YYYY-MM-DD, inclusive; start = travel there, end = travel back):
    {
      "trips": [{"name": "...", "city": "Lisbon", "start": "...", "end": "...",
                 "arrive": "...", "depart": "...", "contact": "...",
                 "sessions": [{"date": "...", "when": "10:00", "title": "...", "place": "..."}],
                 "free_slots": ["Tue afternoon"]}],
      "away": [{"place": "Family visit", "start": "...", "end": "..."}],
      "prep_schedule": [{"days_before": 3, "task": "{city}: ..."}, {"days_after": 1, "task": "..."}]
    }

Placeholders in prep tasks: {city} {name} {titles} {titles_first_half}
{titles_second_half} {free_slots} {arrive}.

While you're away, weekly fixed items (except `away_ok: true` ones) are
listed as skipped, and travel days block the run planner.
"""

from datetime import timedelta

import config

UPCOMING_DAYS = 30


def load(ctx):
    rel = config.get(ctx["cfg"], "trips.file", "data/trips.json")
    try:
        data = config.read_json(rel, None)
    except ValueError as e:
        ctx["warnings"].append(f"{rel} is not valid JSON ({e})")
        data = None
    if data is None:
        ctx["warnings"].append(f"trips is enabled but {rel} is missing or unreadable")
        data = {}
    trips, away = [], []
    for t in data.get("trips") or []:
        s, e = config.to_date(t.get("start")), config.to_date(t.get("end"))
        if not (isinstance(t, dict) and s and e and s <= e):
            ctx["warnings"].append(f"trip {t.get('name', '?')!r} has a bad start/end date, ignored")
            continue
        trips.append(dict(t, start_d=s, end_d=e))
    for a in data.get("away") or []:
        s, e = config.to_date(a.get("start")), config.to_date(a.get("end"))
        if s and e:
            away.append(dict(a, start_d=s, end_d=e))
    prep = [p for p in data.get("prep_schedule") or [] if isinstance(p, dict) and p.get("task")]
    return trips, away, prep


def make_where(trips, away, home):
    def where(d):
        """(location, trip or None, away?) for a date."""
        for t in trips:
            if t["start_d"] <= d <= t["end_d"]:
                return t.get("city") or t.get("name") or "away", t, True
        for a in away:
            if a["start_d"] <= d <= a["end_d"]:
                return a.get("place") or "away", None, True
        return home, None, False
    return where


def task_text(template, t):
    titles = list(dict.fromkeys(s.get("title", "") for s in t.get("sessions", []) if s.get("title")))
    half = (len(titles) + 1) // 2
    fields = {
        "city": t.get("city", ""), "name": t.get("name", ""), "titles": ", ".join(titles),
        "titles_first_half": ", ".join(titles[:half]), "titles_second_half": ", ".join(titles[half:]) or "the rest",
        "free_slots": "; ".join(t.get("free_slots", [])), "arrive": t.get("arrive", ""),
    }
    try:
        return str(template).format(**fields)
    except (KeyError, IndexError, ValueError):
        return str(template)


def facts(ctx):
    today = ctx["today"]
    trips, away, prep = load(ctx)
    where = make_where(trips, away, ctx["home"])
    ctx["where"] = where
    ctx["travel_days"] = {d for t in trips + away for d in (t["start_d"], t["end_d"])}

    loc, trip, is_away = where(today)
    trip_today = None
    if trip:
        trip_today = {
            "name": trip.get("name"), "city": trip.get("city"),
            "day": (today - trip["start_d"]).days + 1, "days": (trip["end_d"] - trip["start_d"]).days + 1,
            "sessions": [s for s in trip.get("sessions", []) if s.get("date") == today.isoformat()],
            "arrival_day": today == trip["start_d"], "departure_day": today == trip["end_d"],
            "arrive": trip.get("arrive"), "depart": trip.get("depart"), "contact": trip.get("contact"),
        }
    tasks = []
    for t in trips:
        before, after = (t["start_d"] - today).days, (today - t["end_d"]).days
        for p in prep:
            hit = (p.get("days_before") is not None and before == int(p["days_before"])) or \
                  (p.get("days_after") is not None and after == int(p["days_after"]))
            if hit:
                tasks.append({"trip": t.get("name"), "city": t.get("city"), "task": task_text(p["task"], t)})
    horizon = today + timedelta(days=UPCOMING_DAYS)
    upcoming = [{"name": t.get("name"), "city": t.get("city"), "start": t["start_d"].isoformat(),
                 "end": t["end_d"].isoformat(), "days_until": (t["start_d"] - today).days}
                for t in sorted(trips, key=lambda t: t["start_d"]) if today < t["start_d"] <= horizon]
    return {"location": loc, "away": is_away, "trip_today": trip_today, "tasks_today": tasks, "upcoming": upcoming}
