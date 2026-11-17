#!/usr/bin/env python3
"""Read data/day_plan.json and report what's planned for a given day.

Usage:
    python3 scripts/plan_status.py data/day_plan.json [--as-of YYYY-MM-DD]

The file is hand-edited (or edited by asking Claude), so this reader is
deliberately forgiving: it NEVER raises. A missing file, invalid JSON, a bad
date or a duplicate day becomes a plain-English entry in `warnings`, and the
brief shows it as a "heads up" line instead of failing the whole delivery.

Output (JSON):
    today_output / today_note         the day's entry (null if none)
    tomorrow_output                   preview of the next day's entry (null if none)
    schedule_changes_today            [{date, text}] dated items for today
    schedule_changes_upcoming         same, for the next UPCOMING_DAYS days
    warnings                          list of problems found in the file

Stdlib only, no network -- same philosophy as calendar_status.py.
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

UPCOMING_DAYS = 3


def _to_date(value, where, warnings):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        warnings.append(f"{where}: date {value!r} is not YYYY-MM-DD, entry ignored")
        return None


def _as_list(data, key, warnings):
    items = data.get(key) or []
    if not isinstance(items, list):
        warnings.append(f"'{key}' should be a list, ignoring it")
        return []
    return items


def plan_facts(path, today):
    out = {
        "today": today.isoformat(),
        "today_output": None,
        "today_note": "",
        "tomorrow_output": None,
        "schedule_changes_today": [],
        "schedule_changes_upcoming": [],
        "warnings": [],
    }
    warnings = out["warnings"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
    except FileNotFoundError:
        warnings.append(f"plan file {os.path.basename(path)} not found")
        return out
    except (OSError, ValueError) as e:  # json.JSONDecodeError is a ValueError
        warnings.append(f"plan file {os.path.basename(path)} could not be read ({e})")
        return out

    days = {}
    for i, entry in enumerate(_as_list(data, "days", warnings)):
        where = f"days[{i}]"
        if not isinstance(entry, dict):
            warnings.append(f"{where}: expected an object, entry ignored")
            continue
        d = _to_date(entry.get("date"), where, warnings)
        output = str(entry.get("output") or "").strip()
        if d is None:
            continue
        if not output:
            warnings.append(f"{where} ({d}): 'output' is empty, entry ignored")
            continue
        if d in days:
            warnings.append(f"{where}: {d} appears more than once, keeping the first")
            continue
        days[d] = {"output": output, "note": str(entry.get("note") or "").strip()}

    changes = []
    for i, entry in enumerate(_as_list(data, "schedule_changes", warnings)):
        where = f"schedule_changes[{i}]"
        if not isinstance(entry, dict):
            warnings.append(f"{where}: expected an object, entry ignored")
            continue
        d = _to_date(entry.get("date"), where, warnings)
        text = str(entry.get("text") or "").strip()
        if d is None:
            continue
        if not text:
            warnings.append(f"{where} ({d}): 'text' is empty, entry ignored")
            continue
        changes.append((d, text))

    if today in days:
        out["today_output"], out["today_note"] = days[today]["output"], days[today]["note"]
    tomorrow = days.get(today + timedelta(days=1))
    out["tomorrow_output"] = tomorrow["output"] if tomorrow else None

    horizon = today + timedelta(days=UPCOMING_DAYS)
    for d, text in sorted(changes):
        item = {"date": d.isoformat(), "text": text}
        if d == today:
            out["schedule_changes_today"].append(item)
        elif today < d <= horizon:
            out["schedule_changes_upcoming"].append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_file")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD, defaults to today in user.timezone")
    args = ap.parse_args()
    if args.as_of:
        today = date.fromisoformat(args.as_of)
    else:
        import config
        today = config.today_local(config.load_profile())
    print(json.dumps(plan_facts(args.plan_file, today), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
