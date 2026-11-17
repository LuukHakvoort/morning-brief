#!/usr/bin/env python3
"""Expand an iCalendar (.ics) feed into the events of a given day or date range.

Usage:
    python3 scripts/calendar_status.py <file.ics> [--as-of YYYY-MM-DD] [--tz Area/City]
    python3 scripts/calendar_status.py <file.ics> --from YYYY-MM-DD --to YYYY-MM-DD

Works with any standard feed (iCloud, Google, Outlook, Fastmail...). Stdlib
only, no network: fetching is scripts/calendar_refresh.py's job. Times are
reported in the brief's timezone (user.timezone unless --tz is given), so an
event stored in UTC shows up at the right local time.

RRULE support is deliberately bounded, not a full RFC 5545 engine:
  In scope:  FREQ=DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL,
             simple BYDAY weekday lists (WEEKLY only, e.g. MO,WE,FR),
             BYMONTHDAY (MONTHLY only, positive values only).
  Out of scope (routed to `unsupported_rrules_skipped`, never guessed):
             BYSETPOS, BYWEEKNO, BYYEARDAY, ordinal BYDAY (e.g. "2TH"),
             negative BYMONTHDAY, sub-daily FREQ.
A moved/cancelled single occurrence (RECURRENCE-ID) is handled: it
suppresses the master series' occurrence on its original date, and (unless
STATUS:CANCELLED) is emitted as its own one-off event on its own DTSTART.
Unknown TZIDs (e.g. Outlook's Windows zone names) fall back to the brief's
timezone.
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
SAFETY_CAP = 100_000
DURATION_RE = re.compile(r"^([+-]?)P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


# ---------- RFC 5545 low-level parsing ----------

def unfold(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for line in text.split("\n"):
        if line.startswith((" ", "\t")) and out:
            out[-1] += line[1:]
        elif line == "":
            continue
        else:
            out.append(line)
    return out


def parse_line(line):
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v
    return name, params, value


def parse_components(lines):
    """Return a list of VEVENT dicts: {PROPNAME: [(params, value), ...]}"""
    events = []
    current = None
    for line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "BEGIN":
            if value == "VEVENT":
                current = {}
            continue
        if name == "END":
            if value == "VEVENT" and current is not None:
                events.append(current)
                current = None
            continue
        if current is not None:
            current.setdefault(name, []).append((params, value))
    return events


def get1(props, name):
    vals = props.get(name)
    return vals[0][1] if vals else None


def parse_dt(params, value, default_tz):
    if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
        y, m, d = int(value[0:4]), int(value[4:6]), int(value[6:8])
        return {"all_day": True, "date": date(y, m, d)}
    v = value
    tzinfo = None
    if v.endswith("Z"):
        v = v[:-1]
        tzinfo = timezone.utc
    tzid = params.get("TZID")
    y, m, d = int(v[0:4]), int(v[4:6]), int(v[6:8])
    hh, mm, ss = int(v[9:11]), int(v[11:13]), int(v[13:15])
    naive = datetime(y, m, d, hh, mm, ss)
    if tzinfo is not None:
        dt = naive.replace(tzinfo=tzinfo)
    elif tzid:
        try:
            dt = naive.replace(tzinfo=ZoneInfo(tzid))
        except Exception:
            dt = naive.replace(tzinfo=default_tz)
    else:
        dt = naive.replace(tzinfo=default_tz)
    return {"all_day": False, "dt": dt}


def parse_duration(value):
    m = DURATION_RE.match(value)
    if not m:
        return None
    sign, days, hours, minutes, seconds = m.groups()
    total = timedelta(days=int(days or 0), hours=int(hours or 0),
                       minutes=int(minutes or 0), seconds=int(seconds or 0))
    return -total if sign == "-" else total


# ---------- RRULE handling ----------

def parse_rrule(value):
    parts = {}
    for token in value.split(";"):
        if "=" in token:
            k, v = token.split("=", 1)
            parts[k.upper()] = v
    return parts


def rrule_supported(parts):
    freq = parts.get("FREQ")
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return False, f"unsupported FREQ={freq}"
    if any(k in parts for k in ("BYSETPOS", "BYWEEKNO", "BYYEARDAY")):
        return False, "unsupported BY* rule (BYSETPOS/BYWEEKNO/BYYEARDAY)"
    byday = parts.get("BYDAY")
    if byday:
        if freq != "WEEKLY":
            return False, "BYDAY only supported for FREQ=WEEKLY"
        for tok in byday.split(","):
            if re.search(r"[+-]?\d", tok):
                return False, f"unsupported ordinal BYDAY ({tok})"
    bymonthday = parts.get("BYMONTHDAY")
    if bymonthday:
        if freq != "MONTHLY":
            return False, "BYMONTHDAY only supported for FREQ=MONTHLY"
        for tok in bymonthday.split(","):
            if int(tok) < 0:
                return False, f"unsupported negative BYMONTHDAY ({tok})"
    return True, None


def generate_dates(dtstart_date, freq, interval, byday, bymonthday, count, until_date, state):
    n = 0
    if freq == "DAILY":
        cur = dtstart_date
        while True:
            if n >= SAFETY_CAP:
                state["truncated"] = True
                return
            if until_date and cur > until_date:
                return
            if count is not None and n >= count:
                return
            yield cur
            n += 1
            cur += timedelta(days=interval)
    elif freq == "WEEKLY":
        if byday:
            week_start = dtstart_date - timedelta(days=dtstart_date.weekday())
            while True:
                if n >= SAFETY_CAP:
                    state["truncated"] = True
                    return
                for i, code in enumerate(WEEKDAY_CODES):
                    if code in byday:
                        candidate = week_start + timedelta(days=i)
                        if candidate < dtstart_date:
                            continue
                        if until_date and candidate > until_date:
                            return
                        if count is not None and n >= count:
                            return
                        yield candidate
                        n += 1
                        if n >= SAFETY_CAP:
                            state["truncated"] = True
                            return
                week_start += timedelta(weeks=interval)
        else:
            cur = dtstart_date
            while True:
                if n >= SAFETY_CAP:
                    state["truncated"] = True
                    return
                if until_date and cur > until_date:
                    return
                if count is not None and n >= count:
                    return
                yield cur
                n += 1
                cur += timedelta(weeks=interval)
    elif freq == "MONTHLY":
        days = bymonthday or [dtstart_date.day]
        y, m = dtstart_date.year, dtstart_date.month
        while True:
            if n >= SAFETY_CAP:
                state["truncated"] = True
                return
            candidates = []
            for d in days:
                try:
                    candidates.append(date(y, m, d))
                except ValueError:
                    pass
            candidates.sort()
            for candidate in candidates:
                if candidate < dtstart_date:
                    continue
                if until_date and candidate > until_date:
                    return
                if count is not None and n >= count:
                    return
                yield candidate
                n += 1
                if n >= SAFETY_CAP:
                    state["truncated"] = True
                    return
            m += interval
            while m > 12:
                m -= 12
                y += 1
    elif freq == "YEARLY":
        y = dtstart_date.year
        while True:
            if n >= SAFETY_CAP:
                state["truncated"] = True
                return
            try:
                candidate = date(y, dtstart_date.month, dtstart_date.day)
            except ValueError:
                candidate = None
            if candidate and candidate >= dtstart_date:
                if until_date and candidate > until_date:
                    return
                if count is not None and n >= count:
                    return
                yield candidate
                n += 1
            y += interval


def check_occurrence(dtstart_date, freq, interval, byday, bymonthday, count, until_date, target_date):
    state = {"truncated": False}
    for candidate in generate_dates(dtstart_date, freq, interval, byday, bymonthday, count, until_date, state):
        if candidate == target_date:
            return True, False
        if candidate > target_date:
            return False, False
    return False, state["truncated"]


def shift_to_date(start_norm, end_norm, target_date):
    if start_norm["all_day"]:
        span_days = (end_norm["date"] - start_norm["date"]).days if end_norm else 1
        return ({"all_day": True, "date": target_date},
                {"all_day": True, "date": target_date + timedelta(days=span_days)})
    tzinfo = start_norm["dt"].tzinfo
    new_start = datetime(target_date.year, target_date.month, target_date.day,
                          start_norm["dt"].hour, start_norm["dt"].minute, start_norm["dt"].second,
                          tzinfo=tzinfo)
    duration = (end_norm["dt"] - start_norm["dt"]) if end_norm else timedelta(0)
    return {"all_day": False, "dt": new_start}, {"all_day": False, "dt": new_start + duration}


def _local(norm, tz):
    return norm["dt"].astimezone(tz)


def make_event_dict(props, start_norm, end_norm, recurring, tz):
    all_day = start_norm["all_day"]
    if all_day:
        start_str = start_norm["date"].isoformat()
        end_str = end_norm["date"].isoformat() if end_norm else None
    else:
        start_str = _local(start_norm, tz).isoformat()
        end_str = _local(end_norm, tz).isoformat() if end_norm else None
    return {
        "uid": get1(props, "UID") or "",
        "summary": clean_text(get1(props, "SUMMARY")) or "(no title)",
        "location": clean_text(get1(props, "LOCATION")) or None,
        "all_day": all_day,
        "start": start_str,
        "end": end_str,
        "recurring": recurring,
    }


def clean_text(value):
    r"""Undo iCalendar text escaping (\n \, \;) and collapse whitespace."""
    if value is None:
        return None
    value = value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
    return re.sub(r"\s+", " ", value).strip()


def resolve_end(props, start_norm, tz):
    dtend = props.get("DTEND")
    if dtend:
        eparams, evalue = dtend[0]
        return parse_dt(eparams, evalue, tz)
    duration = props.get("DURATION")
    if duration:
        dur = parse_duration(duration[0][1])
        if dur is not None:
            if start_norm["all_day"]:
                return {"all_day": True, "date": start_norm["date"] + dur}
            return {"all_day": False, "dt": start_norm["dt"] + dur}
    return None


def _own_date(norm):
    """The date in the event's own zone (what RRULE/EXDATE/RECURRENCE-ID count in)."""
    return norm["date"] if norm["all_day"] else norm["dt"].date()


def prepare(ics_text, tz):
    """Parse the feed once; the result can be expanded for many days with events_on()."""
    masters, overrides, warnings = {}, [], []
    for props in parse_components(unfold(ics_text)):
        if "DTSTART" not in props:
            warnings.append("skipped a VEVENT with no DTSTART")
            continue
        uid = get1(props, "UID") or f"no-uid-{len(masters) + len(overrides)}"
        if props.get("RECURRENCE-ID"):
            overrides.append((uid, props))
        elif uid in masters:
            warnings.append(f"duplicate master UID {uid!r}, keeping first")
        else:
            masters[uid] = props
    suppressed, moved = {}, []
    for uid, props in overrides:
        rparams, rvalue = props["RECURRENCE-ID"][0]
        suppressed.setdefault(uid, set()).add(_own_date(parse_dt(rparams, rvalue, tz)))
        status = get1(props, "STATUS")
        if status and status.upper() == "CANCELLED":
            continue
        sparams, svalue = props["DTSTART"][0]
        start_norm = parse_dt(sparams, svalue, tz)
        moved.append((props, start_norm, resolve_end(props, start_norm, tz)))
    series, unsupported = [], []
    for uid, props in masters.items():
        sparams, svalue = props["DTSTART"][0]
        start_norm = parse_dt(sparams, svalue, tz)
        end_norm = resolve_end(props, start_norm, tz)
        skip = set(suppressed.get(uid, set()))
        for eparams, evalue in props.get("EXDATE", []):
            for tok in evalue.split(","):
                skip.add(_own_date(parse_dt(eparams, tok, tz)))
        rule = None
        if props.get("RRULE"):
            rvalue = props["RRULE"][0][1]
            rparts = parse_rrule(rvalue)
            ok, reason = rrule_supported(rparts)
            if not ok:
                unsupported.append({"uid": uid, "summary": clean_text(get1(props, "SUMMARY")), "rrule": rvalue, "reason": reason})
                continue
            u = rparts.get("UNTIL")
            rule = {
                "freq": rparts["FREQ"], "interval": int(rparts.get("INTERVAL", "1")),
                "count": int(rparts["COUNT"]) if "COUNT" in rparts else None,
                "until": date(int(u[0:4]), int(u[4:6]), int(u[6:8])) if u else None,
                "byday": rparts["BYDAY"].split(",") if rparts.get("BYDAY") else None,
                "bymonthday": [int(x) for x in rparts["BYMONTHDAY"].split(",")] if rparts.get("BYMONTHDAY") else None,
            }
        series.append((uid, props, start_norm, end_norm, skip, rule))
    return {"series": series, "moved": moved, "unsupported": unsupported, "warnings": warnings}


def _occurs_overlapping(start_norm, end_norm, target_date, tz):
    if start_norm["all_day"]:
        end_date = end_norm["date"] if end_norm else start_norm["date"] + timedelta(days=1)
        return start_norm["date"] <= target_date < end_date
    end_dt = end_norm["dt"] if end_norm else start_norm["dt"]
    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    return start_norm["dt"] < day_end and (end_dt > day_start or start_norm["dt"] >= day_start)


def events_on(prepared, target_date, tz):
    """(events, warnings) for one local day."""
    out, warnings = [], []
    for props, start_norm, end_norm in prepared["moved"]:
        local_date = start_norm["date"] if start_norm["all_day"] else _local(start_norm, tz).date()
        if local_date == target_date:
            out.append(make_event_dict(props, start_norm, end_norm, True, tz))
    for uid, props, start_norm, end_norm, skip, rule in prepared["series"]:
        if rule is None:
            if _occurs_overlapping(start_norm, end_norm, target_date, tz) and target_date not in skip:
                out.append(make_event_dict(props, start_norm, end_norm, False, tz))
            continue
        # Expand in the event's own zone (RFC 5545), then keep occurrences whose
        # local start falls on target_date: a 23:30 UTC event is next-day in Europe.
        candidates = [target_date] if start_norm["all_day"] else \
            [target_date - timedelta(days=1), target_date, target_date + timedelta(days=1)]
        for cand in candidates:
            if cand in skip:
                continue
            found, truncated = check_occurrence(_own_date(start_norm), rule["freq"], rule["interval"], rule["byday"],
                                                rule["bymonthday"], rule["count"], rule["until"], cand)
            if truncated:
                warnings.append(f"RRULE generation for UID {uid!r} hit the safety cap before resolving {cand}")
            if not found:
                continue
            occ_start, occ_end = shift_to_date(start_norm, end_norm, cand)
            if occ_start["all_day"] or _local(occ_start, tz).date() == target_date:
                out.append(make_event_dict(props, occ_start, occ_end, True, tz))
    out.sort(key=lambda e: ("" if e["all_day"] else "z", e["start"] or "", e["uid"]))
    return out, warnings


def build_events(ics_text, target_date, tz):
    """(events, unsupported_rrules, warnings) for one day. Kept for simple callers."""
    prepared = prepare(ics_text, tz)
    events, warnings = events_on(prepared, target_date, tz)
    return events, prepared["unsupported"], prepared["warnings"] + warnings


def events_between(ics_text, first, last, tz):
    """{iso_date: [events]} for first..last inclusive, plus unsupported rules and warnings."""
    prepared = prepare(ics_text, tz)
    days, warnings = {}, list(prepared["warnings"])
    d = first
    while d <= last:
        evs, w = events_on(prepared, d, tz)
        days[d.isoformat()] = evs
        warnings += w
        d += timedelta(days=1)
    return days, prepared["unsupported"], warnings


def _default_tz():
    try:
        import config
        return config.tz(config.load_profile())
    except Exception:  # noqa: BLE001 -- standalone use without a profile
        return ZoneInfo("UTC")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ics_file")
    ap.add_argument("--as-of", default=None, help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--from", dest="first", help="range start YYYY-MM-DD (with --to)")
    ap.add_argument("--to", dest="last", help="range end YYYY-MM-DD, inclusive")
    ap.add_argument("--tz", default=None, help="IANA zone, default user.timezone from config/profile.yaml")
    args = ap.parse_args()

    tz = ZoneInfo(args.tz) if args.tz else _default_tz()
    with open(args.ics_file, "r", encoding="utf-8", errors="replace") as f:
        ics_text = f.read()
    if args.first and args.last:
        days, unsupported, warnings = events_between(ics_text, date.fromisoformat(args.first),
                                                     date.fromisoformat(args.last), tz)
        result = {"timezone": str(tz), "days": days, "unsupported_rrules_skipped": unsupported,
                  "parse_warnings": warnings}
    else:
        target_date = date.fromisoformat(args.as_of) if args.as_of else datetime.now(tz).date()
        events, unsupported, warnings = build_events(ics_text, target_date, tz)
        result = {"as_of": target_date.isoformat(), "timezone": str(tz), "events": events,
                  "event_count": len(events), "unsupported_rrules_skipped": unsupported,
                  "parse_warnings": warnings}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
