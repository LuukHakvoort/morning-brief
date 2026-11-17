"""Workout: a daily short workout from a rotation, plus an optional weekly run plan.

profile.yaml:
    workout:
      enabled: true
      minutes: 15
      rotation:                    # "description | optional link", one per day, cycling
        - "Core circuit: plank, dead bug, side plank | https://www.youtube.com/watch?v=..."
      runs:
        enabled: false
        per_week: 2                # one "long" (prefers the weekend) and the rest "easy"
        min_days_between: 2
        evening_starts: "17:00"    # timed calendar events from this time on block that evening
        easy: "30 minutes easy, at a pace where you can talk in full sentences"
        long: "45-60 minutes steady and easy"
        warm_up: "5-minute warm-up | https://..."
        cool_down: "Post-run stretch | https://..."
        block_all_day_keywords: ["trip", "flight", "wedding"]

The run plan for an ISO week is stored in state/history.json `running` by
`facts.py --save`, so it stays stable all week. It's only re-planned when a
planned evening becomes blocked (a new evening event, a trip...).
"""

from datetime import timedelta

import config
import rotations
from week_ahead import WEEKDAYS, ev_times, hm, short


def day_status(ctx, d, runs):
    """(blocked_reason or None, score, long_ok, note) for an evening run on d."""
    evening = hm(runs.get("evening_starts"), "17:00")
    keywords = [str(k).lower() for k in config.as_list(runs.get("block_all_day_keywords"))]
    loc, trip, away = ctx["where"](d)
    if d in ctx["travel_days"]:
        return f"travel day ({loc})", 0, False, ""
    for ev in ctx["cal"].events(d, away=away):
        name = ev["summary"]
        if ev.get("all_day"):
            if any(k in name.lower() for k in keywords):
                return f"all day: {name}", 0, False, ""
            continue
        s, e = ev_times(ev)
        if s is None or (e and (e - s) < timedelta(minutes=30)):
            continue
        if s.time() >= evening or (e and e.date() == d and e.time() >= hm("19:00")):
            return f"evening: {name} {s:%H:%M}", 0, False, ""
    if not away:
        wd = WEEKDAYS[d.weekday()].lower()
        for item in ctx["fixed"]:
            day, time = item["day"].lower(), item["time"]
            if wd in day and ("evening" in day or (time and hm(time[:5], "00:00") >= evening)):
                return f"evening: {item['name']}", 0, False, ""
    score, long_ok, note = 0, True, ""
    if trip:
        score, note = -2, f"in {loc}: run after the day's plans"
    if d.weekday() >= 5:
        score += 1
    return None, score, long_ok, note


def plan_runs(ctx, runs):
    today = ctx["today"]
    per_week = int(runs.get("per_week") or 2)
    gap = int(runs.get("min_days_between") or 2)
    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    monday = today - timedelta(days=today.weekday())
    status = {monday + timedelta(days=i): day_status(ctx, monday + timedelta(days=i), runs) for i in range(7)}
    stored = ctx["history"].get("running") or {}
    stored_plan = stored.get("plan") if stored.get("week") == week and isinstance(stored.get("plan"), list) else None

    note, plan = "", []
    if stored_plan is not None:
        plan = [dict(r) for r in stored_plan if config.to_date(r.get("date"))]
        blocked = [r for r in plan if config.to_date(r["date"]) >= today and status.get(config.to_date(r["date"]), (None,))[0]]
        if not blocked:
            return week, plan, "", status
        for r in blocked:
            d = config.to_date(r["date"])
            note += f"Moved the {r.get('type', 'run')} run off {short(d)} ({status[d][0]}). "
        plan = [r for r in plan if r not in blocked]
    elif today > monday:
        note = "First plan for this week, starting today. "

    taken = [config.to_date(r["date"]) for r in plan]
    remaining = per_week - len(plan)
    if remaining <= 0:
        return week, plan, note.strip(), status
    need = (["long"] if "long" not in [r.get("type") for r in plan] else [])
    need += ["easy"] * (remaining - len(need))
    cands = [x for x in status if x >= today and not status[x][0] and x not in taken]

    def ok_gap(x, chosen, g):
        return all(abs((x - c).days) >= g for c in chosen)

    def pick(kind, chosen):
        for g in (gap, 1):
            pool = [x for x in cands if x not in chosen and ok_gap(x, chosen, g) and (kind != "long" or status[x][2])]
            if pool:
                if kind == "long":
                    return max(pool, key=lambda x: (status[x][1], x.weekday() >= 5, -abs(x.weekday() - 5)))
                return max(pool, key=lambda x: (status[x][1], x.weekday() in (1, 2, 3),
                                                min([abs((x - c).days) for c in chosen] or [7])))
        return None

    if len(cands) < len(need) and "long" in need:  # one free evening left: make it the easy run
        need.remove("long")
        need.append("easy")
    for kind in need:
        x = pick(kind, taken)
        if x is None and kind == "long":
            x, kind = pick("easy", taken), "easy"
        if x is None:
            note += f"Only {len(plan)} run(s) fit this week: no free evening left. "
            break
        taken.append(x)
        plan.append({"date": x.isoformat(), "type": kind,
                     "why": status[x][3] or ("weekend" if x.weekday() >= 5 else "free evening")})
    plan.sort(key=lambda r: r["date"])
    return week, plan, note.strip(), status


def facts(ctx):
    cfg, today = ctx["cfg"], ctx["today"]
    items = [str(x) for x in config.as_list(config.get(cfg, "workout.rotation", [])) if str(x).strip()]
    idx = rotations.pick_index(ctx["history"], "workout", len(items), today)
    out = {"today": None, "_index": idx, "runs": None}
    if items:
        out["today"] = dict(rotations.item_facts(items[idx]), minutes=config.get(cfg, "workout.minutes"))
    else:
        ctx["warnings"].append("workout is enabled but workout.rotation is empty")
    runs = config.get(cfg, "workout.runs", {})
    if isinstance(runs, dict) and runs.get("enabled") is True:
        week, plan, note, status = plan_runs(ctx, runs)
        mine = next((r for r in plan if r["date"] == today.isoformat()), None)
        today_run = None
        if mine:
            kind = mine.get("type", "easy")
            warm, cool = config.split_link(runs.get("warm_up")), config.split_link(runs.get("cool_down"))
            today_run = {"type": kind, "description": str(runs.get("long" if kind == "long" else "easy") or ""),
                         "why": mine.get("why", ""), "warm_up": {"title": warm[0], "url": warm[1]},
                         "cool_down": {"title": cool[0], "url": cool[1]}}
        out["runs"] = {"week": week, "plan": plan, "note": note, "today_run": today_run,
                       "next_run": next((r for r in plan if r["date"] > today.isoformat()), None),
                       "blocked_this_week": {d.isoformat(): s[0] for d, s in status.items() if s[0]}}
    return out


def save(ctx, result, hist):
    rotations.record(hist, "workout", result.get("_index"), ctx["today"])
    if result.get("runs"):
        hist["running"] = {"week": result["runs"]["week"], "plan": result["runs"]["plan"]}
