"""Jobs: today's applications from your own list plus roles the brief found online.

profile.yaml:
    jobs:
      enabled: true
      csv_file: "data/jobs.csv"            # your list (edit in any spreadsheet app, export as CSV)
      pipeline_file: "state/job_pipeline.json"
      daily_picks: 3
      refill_below: 6                      # ask the routine to search for more when fewer are left
      exclude_unpaid: true
      profile_summary: >
        Who you are and what you're looking for, so the routine can judge fit.
      search:
        roles: ["junior data analyst", "research assistant"]
        locations: ["Amsterdam", "remote (EU)"]

data/jobs.csv columns (header row required; extra columns are ignored):
    org, role                  required
    location, url, notes       free text ("notes" is shown as the angle to take)
    deadline                   YYYY-MM-DD
    priority                   1 (top) .. 3, default 2
    status                     open (default) | applied | watch | closed
    pay                        ok | verify | unpaid
    applied_on                 YYYY-MM-DD (for follow-up reminders)

state/job_pipeline.json is written by the routine and by `facts.py --save`:
    items   roles the routine found by web search (same fields as the CSV)
    served  [{key, date}] roles already suggested, so none is suggested twice

Picks: open, not suggested before, not past their deadline, not unpaid (if
exclude_unpaid); ordered by priority, then deadline, then the order in your
list. Re-running on the same day returns the same picks.
"""

import csv
import re
from datetime import date, timedelta

import config

FAR = date(2099, 12, 31)
SERVED_KEEP_DAYS = 180
FOLLOW_UP_DAYS = (7, 21)


def norm(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def make_key(org, role):
    return norm(f"{org} — {role}").lower()


def read_csv(rel, warnings):
    try:
        with open(config.path(rel), "r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        warnings.append(f"jobs is enabled but {rel} doesn't exist")
        return []
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        warnings.append(f"{rel} could not be read ({type(e).__name__}: {e})")
        return []
    out = []
    for row in rows:
        out.append({norm(k).lower(): norm(v) for k, v in row.items() if k})
    return out


def load_pipeline(rel, warnings):
    try:
        data = config.read_json(rel, None)
    except ValueError as e:
        warnings.append(f"{rel} could not be read ({e})")
        data = None
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    data.setdefault("served", [])
    return data


def candidate(raw, source, today):
    deadline = config.to_date(raw.get("deadline"))
    try:
        priority = int(str(raw.get("priority") or "2").strip()[:1])
    except ValueError:
        priority = 2
    pay = norm(raw.get("pay")).lower()
    return {
        "key": str(raw.get("key") or make_key(raw.get("org"), raw.get("role"))).lower(),
        "org": norm(raw.get("org")), "role": norm(raw.get("role")), "location": norm(raw.get("location")),
        "deadline": deadline.isoformat() if deadline else None,
        "days_left": (deadline - today).days if deadline else None,
        "priority": min(max(priority, 1), 3), "pay": pay,
        "pay_note": "check the pay first" if pay == "verify" else "",
        "notes": norm(raw.get("notes") or raw.get("fit_note")), "url": norm(raw.get("url")), "source": source,
    }


def facts(ctx):
    cfg, today, warnings = ctx["cfg"], ctx["today"], ctx["warnings"]
    n_picks = int(config.get(cfg, "jobs.daily_picks", 3))
    exclude_unpaid = config.get(cfg, "jobs.exclude_unpaid", True) is True
    pipeline = load_pipeline(config.get(cfg, "jobs.pipeline_file", "state/job_pipeline.json"), warnings)
    served = {str(s.get("key")).lower(): str(s.get("date") or "")
              for s in pipeline["served"] if isinstance(s, dict) and s.get("key")}

    open_roles, watch, follow_ups, order = [], [], [], {}
    sources = [(r, "your list") for r in read_csv(config.get(cfg, "jobs.csv_file", "data/jobs.csv"), warnings)]
    sources += [(r, "web search") for r in pipeline["items"] if isinstance(r, dict)]
    for i, (raw, source) in enumerate(sources):
        if not raw.get("org") or not raw.get("role"):
            warnings.append(f"a job row from {source} needs at least org and role, ignored")
            continue
        c = candidate(raw, source, today)
        status = norm(raw.get("status") or "open").lower()
        if status == "applied":
            applied = config.to_date(raw.get("applied_on"))
            if applied and FOLLOW_UP_DAYS[0] <= (today - applied).days <= FOLLOW_UP_DAYS[1]:
                follow_ups.append(dict(c, applied_on=applied.isoformat(), days_since=(today - applied).days))
            continue
        if status == "closed" or (c["deadline"] and c["days_left"] < 0):
            continue
        if exclude_unpaid and c["pay"] == "unpaid":
            continue
        if status == "watch":
            watch.append(c)
            continue
        if c["key"] in order:
            continue
        order[c["key"]] = i
        open_roles.append(c)

    open_roles.sort(key=lambda c: (c["priority"], date.fromisoformat(c["deadline"]) if c["deadline"] else FAR,
                                   order[c["key"]]))
    iso = today.isoformat()
    picks = [c for c in open_roles if served.get(c["key"]) == iso]
    for c in open_roles:
        if len(picks) >= n_picks:
            break
        if c["key"] not in served and c not in picks:
            picks.append(c)
    pick_keys = {c["key"] for c in picks}
    closing = [dict(c, suggested_on=served.get(c["key"])) for c in open_roles
               if c["key"] not in pick_keys and c["deadline"] and c["days_left"] <= 7]
    remaining = sum(1 for c in open_roles if c["key"] not in served and c["key"] not in pick_keys)
    return {"todays_picks": picks, "closing_7d": closing, "pipeline_remaining": remaining,
            "needs_refill": remaining < int(config.get(cfg, "jobs.refill_below", n_picks * 2)),
            "follow_ups": follow_ups, "watchlist": watch}


def serve(cfg, today, keys):
    """Record keys as suggested on `today` (idempotent) and prune old entries."""
    rel = config.get(cfg, "jobs.pipeline_file", "state/job_pipeline.json")
    warnings = []
    data = load_pipeline(rel, warnings)
    have = {str(s.get("key")).lower() for s in data["served"] if isinstance(s, dict)}
    for k in keys:
        k = str(k).strip().lower()
        if k and k not in have:
            data["served"].append({"key": k, "date": today.isoformat()})
            have.add(k)
    cutoff = today - timedelta(days=SERVED_KEEP_DAYS)
    data["served"] = [s for s in data["served"]
                      if not (config.to_date(s.get("date")) and config.to_date(s.get("date")) < cutoff)]
    data["items"] = [it for it in data["items"] if not (config.to_date(it.get("deadline"))
                     and config.to_date(it.get("deadline")) < today - timedelta(days=14))]
    data["updated"] = today.isoformat()
    config.write_json(rel, data)
    return warnings


def save(ctx, result, hist):
    keys = ctx.get("serve_jobs") or [c["key"] for c in result.get("todays_picks", [])]
    serve(ctx["cfg"], ctx["today"], keys)
