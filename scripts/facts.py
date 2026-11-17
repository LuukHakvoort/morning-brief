#!/usr/bin/env python3
"""Everything the brief needs to know about today, as one JSON document.

Usage:
    python3 scripts/facts.py [--as-of YYYY-MM-DD]
    python3 scripts/facts.py --save [--serve-jobs KEY ...]   (after the brief is written)

Reads config/profile.yaml, the data/ files and state/history.json. Stdlib
only, no network. Problems never crash it: they become `warnings`, which the
brief turns into one-line heads-ups. Only an unreadable profile.yaml stops it
(exit 1, with the line number of the mistake).

Always present: today, weekday, date_pretty, title_line, is_weekly_extras_day,
user, location, away, calendar, fixed_items_today, skipped_while_away,
day_plan, rotations, week, warnings.
Present when that module is enabled: trips, countdowns, workout, jobs.

--save records what today's brief used, so tomorrow moves on: the rotation
positions, the week's run plan, today's job picks (or the keys given with
--serve-jobs, if the brief swapped one) and last_brief_date. It prints the
same JSON, computed before saving.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import rotations  # noqa: E402
import week_ahead  # noqa: E402
from modules import REGISTRY  # noqa: E402
from plan_status import plan_facts  # noqa: E402


def build(cfg, today, history=None, serve_jobs=None):
    """(facts, ctx). Never raises for data problems."""
    warnings = []
    home = str(config.get(cfg, "user.home_city", "home"))
    ctx = {
        "cfg": cfg, "today": today, "tz": config.tz(cfg), "warnings": warnings,
        "history": config.load_history() if history is None else history,
        "home": home, "fixed": week_ahead.fixed_items(cfg),
        "where": lambda d: (home, None, False), "travel_days": set(),
        "results": {}, "serve_jobs": serve_jobs,
    }
    ctx["cal"] = week_ahead.Calendar(cfg, today, warnings)

    for name, module in REGISTRY:
        if not config.enabled(cfg, name):
            continue
        try:
            ctx["results"][name] = module.facts(ctx)
        except Exception as e:  # noqa: BLE001 -- one broken module must not sink the brief
            warnings.append(f"the {name} module failed ({type(e).__name__}: {e})")

    try:
        rot = rotations.facts(ctx)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"rotations failed ({type(e).__name__}: {e})")
        rot = []
    ctx["rotations"] = rot

    plan_rel = config.get(cfg, "day_plan.file", "data/day_plan.json")
    day_plan = None
    if os.path.exists(config.path(plan_rel)):
        day_plan = plan_facts(config.path(plan_rel), today)
        warnings += [f"day plan: {w}" for w in day_plan.pop("warnings", [])]

    loc, _, away = ctx["where"](today)
    todays_fixed, skipped = week_ahead.fixed_for(ctx, today)
    cal = ctx["cal"]
    extras_day = config.weekly_extras_day(cfg)
    facts = {
        "today": today.isoformat(),
        "weekday": config.WEEKDAYS[today.weekday()],
        "date_pretty": config.pretty_date(today),
        "title_line": f"# {config.brief_title(cfg)} — {config.pretty_date(today)}",
        "is_weekly_extras_day": config.WEEKDAYS[today.weekday()] == extras_day,
        "user": {"name": config.get(cfg, "user.name", ""), "home_city": home},
        "location": loc,
        "away": away,
        "calendar": {"enabled": cal.enabled, "available": cal.available, "generated_at": cal.generated_at,
                     "events_today": cal.events(today, away=away)},
        "fixed_items_today": todays_fixed,
        "skipped_while_away": [f["name"] for f in skipped],
        "day_plan": day_plan,
        "rotations": rot,
    }
    for name, result in ctx["results"].items():
        facts[name] = {k: v for k, v in result.items() if not k.startswith("_")}
    facts["week"] = week_ahead.build_days(ctx)
    facts["warnings"] = warnings
    return facts, ctx


def save(ctx):
    hist = config.load_history()
    rotations.save(ctx, ctx["rotations"], hist)
    for name, module in REGISTRY:
        if name in ctx["results"] and hasattr(module, "save"):
            module.save(ctx, ctx["results"][name], hist)
    hist["last_brief_date"] = ctx["today"].isoformat()
    config.save_history(hist)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--as-of", help="YYYY-MM-DD (default: today in user.timezone)")
    ap.add_argument("--save", action="store_true", help="record today's rotations, runs and job picks")
    ap.add_argument("--serve-jobs", nargs="+", metavar="KEY", help="with --save: the job keys actually shown")
    args = ap.parse_args()
    try:
        cfg = config.load_profile()
    except (config.ConfigError, OSError) as e:
        print(json.dumps({"error": f"config/profile.yaml: {e}"}, indent=2))
        return 1
    today = config.to_date(args.as_of) if args.as_of else config.today_local(cfg)
    if today is None:
        print(json.dumps({"error": f"--as-of {args.as_of!r} is not YYYY-MM-DD"}))
        return 1
    facts, ctx = build(cfg, today, serve_jobs=args.serve_jobs)
    if args.save:
        save(ctx)
    print(json.dumps(facts, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
