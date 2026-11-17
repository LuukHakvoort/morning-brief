#!/usr/bin/env python3
"""Free, no-AI backup edition of the morning brief.

The real brief is written by the Claude cloud routine. If it didn't arrive
(e.g. Claude's usage limit was reached), .github/workflows/deliver.yml runs
this through scripts/deliver.py: a shorter brief assembled purely from
facts.py and free RSS feeds, so a brief always arrives. No AI, no paid API.

It covers whatever modules you enabled (countdown, trip, jobs, the week
ahead on your weekly-extras day), today's shape (plan, fixed items,
calendar, rotations, workout, run) and headline-only news. It can't do the
things that need live research (curated news, finding new jobs) and says so.

Usage:
    python3 scripts/fallback_brief.py [--date YYYY-MM-DD] [--dry-run] [--offline] [--force]

--dry-run prints the brief and writes nothing; --offline skips the news feeds.
Exit codes: 0 wrote the brief; 2 a brief for that date already exists (and
--force wasn't given); 1 error.
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import facts as facts_mod  # noqa: E402
import news_feeds  # noqa: E402

BACKUP_MARKER = ("*Backup edition: the full Claude-written brief didn't come through this morning, so this one "
                 "is assembled automatically: the essentials, with headline-only news and no AI curation.*")
WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_label(iso):
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS_SHORT[d.weekday()]} {config.short_date(d)}"


def link(text, url):
    return f"[{text}]({news_feeds.md_url(url)})" if url else text


def sentence(text):
    text = str(text).strip().rstrip(".")
    return text[:1].upper() + text[1:] + "." if text else ""


def countdown_line(ms):
    unit = "day" if ms["days"] == 1 else "days"
    return f"Countdown check: **{ms['days']} {unit}** to {ms['label']} ({day_label(ms['date'])})."


def event_line(ev):
    name = ev.get("summary") or "(untitled event)"
    if ev.get("all_day"):
        line = f"All day: *{name}*"
        try:
            last = date.fromisoformat(ev["end"]) - timedelta(days=1)
            if last > date.fromisoformat(ev["start"]):
                line += f" (through {config.short_date(last)})"
        except (KeyError, ValueError, TypeError):
            pass
        return line
    try:
        s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
        return f"{s:%H:%M}-{e:%H:%M}: {name}"
    except (KeyError, ValueError, TypeError):
        return name


def fixed_line(item):
    label = item["name"]
    if item.get("time"):
        label += f" ({item['time']})"
    if item.get("note"):
        label += f": {item['note']}"
    return label


def deadline_text(c):
    if not c.get("deadline"):
        return "no deadline listed"
    n = c["days_left"]
    when = "today" if n == 0 else ("tomorrow" if n == 1 else f"in {n} days")
    return f"closes {config.short_date(date.fromisoformat(c['deadline']))} ({when})"


def pick_line(i, c):
    line = f"{i}. **{c['role']}**, {c['org']}" + (f" ({c['location']})" if c.get("location") else "")
    line += " · " + " · ".join([deadline_text(c)] + ([c["pay_note"]] if c.get("pay_note") else [])) + "."
    if c.get("notes"):
        line += f" {config.shorten(c['notes'], 170)}"
    if c.get("url"):
        line += f" {link('Details', c['url'])}"
    return line


def opener(f):
    """(opening line, first move, push teaser): today's single biggest lever."""
    name = f["user"].get("name") or ""
    hey = f"Let's go, {name}!" if name else "Let's go!"
    cd = f.get("countdowns") or {}
    nxt, reminders = cd.get("next"), cd.get("reminders_today") or []
    trip = (f.get("trips") or {}).get("trip_today")
    picks = (f.get("jobs") or {}).get("todays_picks") or []
    plan = (f.get("day_plan") or {}).get("today_output")
    if nxt and nxt["days"] == 0:
        return (f"Today's the day: {nxt['label']}. Everything else can wait.",
                "check the plan for today once, then go.", f"Today's the day: {nxt['label']}.")
    if reminders:
        r = reminders[0]
        days = next((x["days"] for x in cd.get("upcoming", []) if x["label"] == r["label"]), None)
        lead = f"{days} days to {r['label']}" if days else r["label"].capitalize()
        return (f"{hey} {lead}: today, {r['text'][:1].lower() + r['text'][1:].rstrip('.')}.",
                f"{r['text'][:1].lower() + r['text'][1:].rstrip('.')}.", f"Backup brief: {r['text']}")
    if trip:
        return (f"{hey} Day {trip['day']} of {trip['days']} in {trip['city']}: make every session count.",
                "re-read today's agenda and note one question per session.",
                f"Backup brief: day {trip['day']} in {trip['city']}.")
    if picks:
        p = picks[0]
        return (f"{hey} Today's lever: {len(picks)} application{'s' if len(picks) > 1 else ''}, starting with "
                f"{p['role']} at {p['org']}.", f"open the first application: {p['role']} at {p['org']}.",
                f"Backup brief: first application today is {p['role']} at {p['org']}.")
    if plan:
        return (f"{hey} Today's lever: {plan[:1].lower() + plan[1:].rstrip('.')}.",
                f"start on it: {plan[:1].lower() + plan[1:].rstrip('.')}.",
                f"Backup brief: today's lever is {plan[:1].lower() + plan[1:].rstrip('.')}.")
    if nxt:
        return (f"{hey} {nxt['days']} days to {nxt['label']}: that's {nxt['days']} chances to get closer.",
                "pick the one task that moves it forward and start it.",
                f"Backup brief: {nxt['days']} days to {nxt['label']}.")
    return (f"{hey} Your brief is ready: one clear day ahead.", "pick today's most important task and start it.",
            "Backup brief: your morning brief is ready.")


def countdown_section(f):
    cd = f.get("countdowns") or {}
    if not cd.get("next") and not cd.get("reminders_today"):
        return []
    L = ["## Countdown", ""]
    if cd.get("next"):
        L += [countdown_line(cd["next"]), ""]
    if cd.get("reminders_today"):
        L += ["**Today on the way there:**"] + [f"- {sentence(r['text'])[:-1]} ({r['label']})." for r in cd["reminders_today"]] + [""]
    later = [c for c in cd.get("upcoming", [])[1:4]]
    if later:
        L += ["After that: " + "; ".join(f"{c['label']} ({day_label(c['date'])})" for c in later) + ".", ""]
    return L


def trip_section(f):
    tr = f.get("trips") or {}
    t, tasks = tr.get("trip_today"), tr.get("tasks_today") or []
    if not t and not tasks:
        return []
    L = ["## Trip", ""]
    if t:
        L += [f"**{t['city']}, day {t['day']} of {t['days']}:**"]
        L += [f"- {s.get('when', '')}: {s.get('title', '')}" + (f", {s['place']}" if s.get("place") else "") for s in t["sessions"]]
        if t["arrival_day"] and t.get("arrive"):
            L.append(f"- Arrival: {t['arrive']}.")
        if t["departure_day"] and t.get("depart"):
            L.append(f"- Departure: {t['depart']}.")
        L.append("")
    for task in tasks:
        L += [f"**Prep:** {task['task']}", ""]
    return L


def jobs_section(f):
    j = f.get("jobs")
    if j is None:
        return []
    L = ["## Jobs", ""]
    picks = j.get("todays_picks") or []
    if picks:
        L += [f"**Today's {len(picks)} application{'s' if len(picks) > 1 else ''}:**"]
        L += [pick_line(i, c) for i, c in enumerate(picks, 1)] + [""]
        if (f.get("trips") or {}).get("trip_today"):
            L += ["You're travelling today, so do them this evening.", ""]
    else:
        L += ["- Heads up: no open roles left in your list. Finding new ones needs live research, so add a few "
              "to data/jobs.csv or let tomorrow's full brief refill the queue.", ""]
    if j.get("closing_7d"):
        L += ["**Also closing this week:** " + "; ".join(
            f"{c['org']}, {c['role']} ({config.short_date(date.fromisoformat(c['deadline']))})" for c in j["closing_7d"][:5]) + ".", ""]
    if j.get("follow_ups"):
        L += ["**Follow up:** " + "; ".join(f"{c['org']}, {c['role']} (applied {c['days_since']} days ago)"
                                            for c in j["follow_ups"][:3]) + ".", ""]
    if f.get("is_weekly_extras_day"):
        L += [f"{j.get('pipeline_remaining', 0)} open roles are queued after today's picks."]
        if j.get("watchlist"):
            L += ["**Watchlist:** " + "; ".join(f"{c['org']}, {c['role']}" for c in j["watchlist"][:4]) + "."]
        L += ["", "- Heads up: the weekly refill with new roles needs live web research, so the backup edition skips it.", ""]
    return L


def week_section(f):
    L = ["## Week ahead", ""]
    for d in f["week"]:
        bits = []
        if d["away"]:
            bits.append(f"in {d['location']}" + (" (travel)" if d["travel"] else ""))
        bits += d["sessions"] + d["countdowns"] + d["fixed_items"] + d["events"][:3]
        if d["run"]:
            bits.append(f"run ({'longer' if d['run'] == 'long' else 'easy'})")
        L.append(f"- **{day_label(d['date'])}**: " + ("; ".join(bits) if bits else "nothing fixed"))
    note = (((f.get("workout") or {}).get("runs")) or {}).get("note")
    if note:
        L.append(f"- Runs: {note}")
    return L + [""]


def shape_section(f):
    L = ["## Today's shape", ""]
    plan = f.get("day_plan") or {}
    if plan.get("today_output"):
        note = f" ({plan['today_note']})" if plan.get("today_note") else ""
        L += [f"**Today's focus:** {plan['today_output'].rstrip('.')}{note}."]
        if plan.get("tomorrow_output"):
            L += [f"Tomorrow: {plan['tomorrow_output'].rstrip('.')}."]
        L += [""]
    if plan.get("schedule_changes_today"):
        L += ["**Schedule changes today:**"] + [f"- {c['text']}" for c in plan["schedule_changes_today"]] + [""]
    if plan.get("schedule_changes_upcoming"):
        L += ["**Coming up:**"] + [f"- {config.short_date(date.fromisoformat(c['date']))}: {c['text']}"
                                   for c in plan["schedule_changes_upcoming"]] + [""]
    if f["skipped_while_away"]:
        L += [f"**Away in {f['location']}:** skipped today: {', '.join(f['skipped_while_away'])}.", ""]
    if f["fixed_items_today"]:
        L += ["**Fixed today:**"] + [f"- {fixed_line(i)}" for i in f["fixed_items_today"]] + [""]
    cal = f["calendar"]
    if cal["enabled"]:
        fixed = [i["name"].lower() for i in f["fixed_items_today"]]
        shown = [ev for ev in cal["events_today"]
                 if not any(n in (ev.get("summary") or "").lower() for n in fixed)]
        if not cal["available"]:
            L += ["Heads up: the calendar wasn't available today, so check it yourself.", ""]
        elif shown:
            L += ["**Calendar:**"] + [f"- {event_line(ev)}" for ev in shown] + [""]
    for r in f["rotations"]:
        mins = f" ({r['minutes']} min)" if r.get("minutes") else ""
        L += [f"**{r['name']}{mins}:** {sentence(link(r['text'], r['url']))}", ""]
    w = f.get("workout") or {}
    if w.get("today"):
        mins = f" ({w['today']['minutes']} min)" if w["today"].get("minutes") else ""
        L += [f"**Workout{mins}:** {sentence(link(w['today']['text'], w['today']['url']))}", ""]
    runs = w.get("runs") or {}
    run = runs.get("today_run")
    if run:
        kind = "longer run" if run["type"] == "long" else "easy run"
        why = f" ({run['why']})" if run.get("why") and run["why"] not in ("free evening", "weekend") else ""
        extras = []
        if run["warm_up"]["title"]:
            extras.append(f"Warm-up: {link(run['warm_up']['title'], run['warm_up']['url'])}.")
        if run["cool_down"]["title"]:
            extras.append(f"After: {link(run['cool_down']['title'], run['cool_down']['url'])}.")
        L += [f"**Run this evening, {kind}:** {run['description'].rstrip('.')}{why}. " + " ".join(extras), ""]
    elif runs.get("next_run"):
        nr = runs["next_run"]
        L += [f"**Next run:** {day_label(nr['date'])} evening ({'longer' if nr['type'] == 'long' else 'easy'}).", ""]
    if f["warnings"]:
        L += [f"Heads up: {w_}." if not w_.endswith(".") else f"Heads up: {w_}" for w_ in f["warnings"][:3]] + [""]
    return L


def build_brief(f, cfg, news):
    """(markdown, teaser)"""
    first_line, first_move, teaser = opener(f)
    L = [f["title_line"], "", first_line, "", BACKUP_MARKER, ""]
    L += countdown_section(f) + trip_section(f) + jobs_section(f)
    if f["is_weekly_extras_day"]:
        L += week_section(f)
    L += shape_section(f)
    heading = str(config.get(cfg, "news.section_heading", "World pulse"))
    L += [f"## {heading}", ""] + news_feeds.bullets(news) + [""]
    L += ["## Closing kick", "", f"**First move for the next 30 minutes:** {first_move}", ""]
    return "\n".join(L).rstrip() + "\n", config.shorten(teaser, 190)


def build_and_write(today, force=False, offline=False):
    """Build, save and record today's backup brief. Returns the teaser, or None if the brief exists."""
    out_path = config.path(f"briefs/{today.isoformat()}.md")
    if os.path.exists(out_path) and not force:
        return None
    cfg = config.load_profile()
    f, ctx = facts_mod.build(cfg, today)
    news = {"headlines": [], "reports": [], "failed": 0, "total": 0} if offline else news_feeds.news_items(cfg, today)
    brief, teaser = build_brief(f, cfg, news)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(brief)
    facts_mod.save(ctx)
    config.log(f"wrote {out_path}")
    return teaser


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", help="YYYY-MM-DD (default: today in user.timezone)")
    ap.add_argument("--dry-run", action="store_true", help="print the brief; write nothing")
    ap.add_argument("--offline", action="store_true", help="skip the news feeds")
    ap.add_argument("--force", action="store_true", help="overwrite an existing briefs/<date>.md")
    args = ap.parse_args()
    cfg = config.load_profile()
    today = config.to_date(args.date) if args.date else config.today_local(cfg)
    if args.dry_run:
        f, _ = facts_mod.build(cfg, today)
        news = {"headlines": [], "reports": [], "failed": 0, "total": 0} if args.offline else news_feeds.news_items(cfg, today)
        brief, teaser = build_brief(f, cfg, news)
        print(brief)
        config.log(f"teaser: {teaser}")
        return 0
    if build_and_write(today, args.force, args.offline) is None:
        config.log(f"briefs/{today.isoformat()}.md already exists; not overwriting (use --force)")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
