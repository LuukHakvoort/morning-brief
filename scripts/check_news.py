#!/usr/bin/env python3
"""Check a brief's World pulse: every bullet dated, recent, and not repeated.

Usage:
    python3 scripts/check_news.py briefs/2026-10-03.md [--json]

Each bullet of the news section (`## <news.section_heading>`, default
"World pulse") must:
  1. carry a source link;
  2. have a date (in the URL or the text) within `news.max_age_days` of the
     brief's date -- a month-only URL counts as out of window when it names a
     different month than the brief's;
  3. not repeat a link already used in the World pulse of any brief from the
     previous `news.dedupe_window_days`.

Exit 1 when there are problems (so the routine can fix its bullets and re-run);
exit 0 otherwise. Never raises: an internal error is reported in the JSON as
`checker_error` and exits 0, so a checker bug can never block delivery.

Also importable: the backup brief uses `recent_links()` and `item_is_fresh()`
so its own feeds follow the same rules.
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "oct": 10, "nov": 11, "dec": 12}
MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
YEAR = r"(20\d\d)"
TEXT_DAY_MON = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{MON}\.?\b(?:,?\s+{YEAR})?", re.IGNORECASE)
TEXT_MON_DAY = re.compile(rf"\b{MON}\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+{YEAR})?", re.IGNORECASE)
URL_FULL = re.compile(rf"/{YEAR}/(\d{{1,2}})/(\d{{1,2}})(?:/|\b)")
URL_FULL_NAMED = re.compile(rf"/{YEAR}/{MON}/(\d{{1,2}})(?:/|\b)", re.IGNORECASE)
URL_ISO = re.compile(rf"{YEAR}-(\d{{2}})-(\d{{2}})")
URL_MONTH = re.compile(rf"/{YEAR}/(\d{{1,2}})/")
LINK_RE = re.compile(r"https?://[^\s)\]>\"']+")


def _month(token):
    return MONTHS[token[:3].lower()]


def _safe_date(y, m, d):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def normalise_url(url):
    """Comparable form of a link: no query string, fragment or trailing slash."""
    url = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return url.lower()


def dates_in(text, brief_year):
    """Full dates (and month-only markers) found in a URL or a bullet's text."""
    found = []  # (date or None, month_only_tuple or None)
    for m in URL_FULL.finditer(text):
        found.append((_safe_date(m.group(1), m.group(2), m.group(3)), None))
    for m in URL_FULL_NAMED.finditer(text):
        found.append((_safe_date(m.group(1), _month(m.group(2)), m.group(3)), None))
    for m in URL_ISO.finditer(text):
        found.append((_safe_date(m.group(1), m.group(2), m.group(3)), None))
    for m in URL_MONTH.finditer(text):
        found.append((None, (int(m.group(1)), int(m.group(2)))))
    for m in TEXT_DAY_MON.finditer(text):
        found.append((_safe_date(m.group(3) or brief_year, _month(m.group(2)), m.group(1)), None))
    for m in TEXT_MON_DAY.finditer(text):
        found.append((_safe_date(m.group(3) or brief_year, _month(m.group(1)), m.group(2)), None))
    return [f for f in found if f[0] or f[1]]


def item_is_fresh(text, today, max_age_days):
    """(fresh: bool, reason: str) for one bullet/item, judged against the brief date."""
    found = dates_in(text, today.year)
    if not found:
        return False, "no date found (add the event date)"
    cutoff = today - timedelta(days=max_age_days)
    dated = [d for d, _ in found if d and d <= today + timedelta(days=1)]
    if dated:
        newest = max(dated)
        if newest < cutoff:
            return False, f"dated {newest.isoformat()}, older than {max_age_days} days"
        return True, ""
    for _, (y, mth) in found:  # month-only URLs
        if (y, mth) != (today.year, today.month):
            return False, f"month-only date {y}-{mth:02d} from a different month than the brief"
    return True, ""


def world_pulse(text, heading="World pulse"):
    """The news bullets of the `## <heading>` section.

    "Heads up" bullets are plain notices (e.g. "fewer fresh headlines today"),
    not news, so they are skipped.
    """
    m = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return []
    bullets, cur = [], None
    for line in m.group(1).splitlines():
        if line.startswith("- "):
            if cur:
                bullets.append(cur)
            cur = line[2:].strip()
        elif cur and line.strip():
            cur += " " + line.strip()
    if cur:
        bullets.append(cur)
    return [b for b in bullets if not b.lower().startswith("heads up")]


def recent_briefs(today, days, briefs_dir=None):
    briefs_dir = briefs_dir or config.path("briefs")
    out = []
    for path in sorted(glob.glob(os.path.join(briefs_dir, "*.md"))):
        m = re.match(r"(\d{4}-\d{2}-\d{2})\.md$", os.path.basename(path))
        if not m:
            continue
        d = date.fromisoformat(m.group(1))
        if today - timedelta(days=days) <= d < today:
            out.append((d, path))
    return out


def recent_links(today, days, briefs_dir=None, heading="World pulse"):
    """Normalised links used in the World pulse of recent briefs (for de-duplication)."""
    used = set()
    for _, path in recent_briefs(today, days, briefs_dir):
        with open(path, encoding="utf-8") as f:
            for bullet in world_pulse(f.read(), heading):
                used.update(normalise_url(u) for u in LINK_RE.findall(bullet))
    return used


def check_brief(path, max_age_days=7, dedupe_days=7, briefs_dir=None, heading="World pulse"):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    if not m:
        raise ValueError("the brief's file name must contain its date (YYYY-MM-DD)")
    today = date.fromisoformat(m.group(1))
    bullets = world_pulse(text, heading)
    used = recent_links(today, dedupe_days, briefs_dir, heading)
    problems = []
    for b in bullets:
        head = b[:90] + ("…" if len(b) > 90 else "")
        links = [normalise_url(u) for u in LINK_RE.findall(b)]
        if not links:
            problems.append({"bullet": head, "problem": "no source link"})
        fresh, reason = item_is_fresh(b, today, max_age_days)
        if not fresh:
            problems.append({"bullet": head, "problem": reason})
        repeats = [u for u in links if u in used]
        if repeats:
            problems.append({"bullet": head, "problem": "repeats a source from the last "
                             f"{dedupe_days} days of briefs"})
    return {"brief": os.path.relpath(path, config.root()), "date": today.isoformat(),
            "bullets": len(bullets), "problems": problems, "ok": not problems}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brief_file")
    ap.add_argument("--json", action="store_true", help="(default output is JSON; kept for clarity)")
    args = ap.parse_args()
    try:
        cfg = config.load_profile()
        result = check_brief(args.brief_file, int(config.get(cfg, "news.max_age_days", 7)),
                             int(config.get(cfg, "news.dedupe_window_days", 7)),
                             heading=str(config.get(cfg, "news.section_heading", "World pulse")))
    except Exception as e:  # noqa: BLE001 -- a checker bug must never block delivery
        print(json.dumps({"ok": True, "checker_error": f"{type(e).__name__}: {e}", "problems": []}, indent=2))
        return 0
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
