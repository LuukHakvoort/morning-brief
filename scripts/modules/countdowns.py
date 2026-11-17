"""Countdowns: the dates you're working towards, and reminders on the way.

profile.yaml:
    countdowns:
      enabled: true
      include_trips: true          # upcoming trips (trips module) count as milestones too
      items:
        - label: "the half marathon"
          date: "2027-04-11"
          reminders:               # "N | text": shown N days before the date (0 = on the day)
            - "14 | Book the hotel near the start"
            - "1 | Lay out the kit and get an early night"

Output: `next` (what the brief's "Countdown check: **N days** to ..." line
counts down to), `upcoming` (next 60 days) and `reminders_today`.
Past items are ignored (scripts/doctor.py flags them so you can tidy up).
"""

import re
from datetime import timedelta

import config

HORIZON_DAYS = 60


def facts(ctx):
    today, cfg = ctx["today"], ctx["cfg"]
    items, reminders = [], []
    for i, it in enumerate(config.as_list(config.get(cfg, "countdowns.items", []))):
        d = config.to_date(it.get("date")) if isinstance(it, dict) else None
        if not d or not it.get("label"):
            ctx["warnings"].append(f"countdowns.items[{i}] needs a label and a YYYY-MM-DD date, ignored")
            continue
        if d < today:
            continue
        days = (d - today).days
        items.append({"label": str(it["label"]), "date": d.isoformat(), "days": days})
        for r in config.as_list(it.get("reminders")):
            m = re.match(r"^\s*(\d+)\s*\|\s*(.+)$", str(r))
            if not m:
                ctx["warnings"].append(f"countdown reminder {r!r} should look like '3 | text', ignored")
            elif int(m.group(1)) == days:
                reminders.append({"label": str(it["label"]), "text": m.group(2).strip()})
    if config.get(cfg, "countdowns.include_trips", True) is True:
        for t in (ctx["results"].get("trips") or {}).get("upcoming", []):
            items.append({"label": f"your {t.get('city') or t.get('name') or 'next'} trip",
                          "date": t["start"], "days": t["days_until"]})
    items.sort(key=lambda x: (x["date"], x["label"]))
    horizon = (today + timedelta(days=HORIZON_DAYS)).isoformat()
    return {"next": items[0] if items else None,
            "upcoming": [x for x in items if x["date"] <= horizon],
            "reminders_today": reminders}
