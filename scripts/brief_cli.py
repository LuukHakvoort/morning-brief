#!/usr/bin/env python3
"""Terminal helper for browsing past morning briefs.

Usage:
    python3 brief_cli.py list              List all archived briefs, newest first
    python3 brief_cli.py show [DATE]       Show one brief (default: most recent)
    python3 brief_cli.py latest            Alias for `show` with no date

DATE is YYYY-MM-DD, matching a briefs/<DATE>.md filename.
"""

import argparse
import re
import sys
from pathlib import Path

BRIEFS_DIR = Path(__file__).parent.parent / "briefs"
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def all_briefs():
    if not BRIEFS_DIR.exists():
        return []
    dated = []
    for p in BRIEFS_DIR.iterdir():
        m = DATE_RE.match(p.name)
        if m:
            dated.append((m.group(1), p))
    return sorted(dated, key=lambda t: t[0], reverse=True)


def first_line_preview(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:100]
    return ""


def cmd_list(_args):
    briefs = all_briefs()
    if not briefs:
        print("No briefs found in briefs/. Run `git pull` to fetch the latest.")
        return
    for date, path in briefs:
        preview = first_line_preview(path)
        print(f"{date}  {preview}")


def cmd_show(args):
    briefs = all_briefs()
    if not briefs:
        print("No briefs found in briefs/. Run `git pull` to fetch the latest.")
        sys.exit(1)
    if args.date:
        match = next((p for d, p in briefs if d == args.date), None)
        if match is None:
            print(f"No brief found for {args.date}. Available dates:")
            for d, _ in briefs:
                print(f"  {d}")
            sys.exit(1)
    else:
        _, match = briefs[0]
    print(match.read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List all archived briefs, newest first")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one brief (default: most recent)")
    p_show.add_argument("date", nargs="?", default=None, help="YYYY-MM-DD, defaults to latest")
    p_show.set_defaults(func=cmd_show)

    p_latest = sub.add_parser("latest", help="Show the most recent brief")
    p_latest.set_defaults(func=lambda args: cmd_show(argparse.Namespace(date=None)))

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
