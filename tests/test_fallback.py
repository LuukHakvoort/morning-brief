import os
import re
import unittest
from datetime import date, datetime, timezone

from _helpers import FIXTURES, REPO, TempRoot, config

import check_news
import facts
import fallback_brief
import news_feeds

D = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
# Signs of a template bug leaking into the text: unfilled placeholders, Python None, tracebacks.
LEAKS = re.compile(r"\bNone\b|\{[a-z_]+\}|Traceback|\bnull\b")


def fake_fetch(url):
    with open(os.path.join(FIXTURES, "feeds", "rss.xml" if "rss" in url else "atom.xml"), "rb") as f:
        return news_feeds.parse_feed(f.read())


class Feeds(unittest.TestCase):
    def test_rss_and_atom_parse_newest_first(self):
        items = fake_fetch("rss")
        self.assertEqual(items[0]["title"], "Second story & more")
        self.assertIsNone(items[-1]["when"])
        self.assertEqual(fake_fetch("atom")[0]["link"], "https://atom.example/2026/11/14/entry")

    def test_round_robin_and_freshness(self):
        items = news_feeds.fresh_items(fake_fetch("rss"), NOW, 7, used=set())
        self.assertEqual([i["title"] for i in items], ["Second story & more", "First story"])  # stale/undated dropped
        picked = news_feeds.pick_round_robin([("A", [1, 2, 3]), ("B", [4])], 3)
        self.assertEqual(picked, [("A", 1), ("B", 4), ("A", 2)])


class BackupBrief(TempRoot):
    def news(self):
        return news_feeds.news_items(self.cfg(), D, fetch=lambda url: fake_fetch(url), now=NOW)

    def build(self):
        f, ctx = facts.build(self.cfg(), D, history={})
        return fallback_brief.build_brief(f, self.cfg(), self.news())

    def test_default_profile_brief(self):
        brief, teaser = self.build()
        self.assertTrue(brief.startswith("# Morning Brief — Monday, November 16, 2026\n"))
        self.assertIn("Backup edition:", brief)
        self.assertIn("Countdown check: **314 days** to the half marathon", brief)
        self.assertIn("## World pulse", brief)
        self.assertIn("Let's go, Alex!", brief)
        self.assertLessEqual(len(teaser), 190)
        self.assertIsNone(LEAKS.search(brief), brief)

    def test_news_section_passes_the_checker(self):
        brief, _ = self.build()
        self.write_text(f"briefs/{D}.md", brief)
        result = check_news.check_brief(self.path(f"briefs/{D}.md"))
        self.assertTrue(result["ok"], result)
        self.assertGreater(result["bullets"], 0)

    def test_everything_enabled(self):
        self.enable("trips", "jobs", "calendar")
        self.edit_profile("  runs:\n    enabled: false", "  runs:\n    enabled: true")
        self.write_json("data/calendar_window.json", {"generated_at": config.now_local(self.cfg()).isoformat(),
                                                      "first": "2026-11-16", "last": "2026-11-30", "days": {}})
        brief, _ = self.build()
        for heading in ("## Countdown", "## Jobs", "## Week ahead", "## Today's shape", "## Closing kick"):
            self.assertIn(heading, brief)
        self.assertIn("Junior Climate Analyst", brief)
        self.assertIsNone(LEAKS.search(brief), brief)

    def test_build_and_write_saves_state_and_refuses_to_overwrite(self):
        teaser = fallback_brief.build_and_write(D, offline=True)
        self.assertTrue(teaser)
        self.assertTrue(os.path.exists(self.path(f"briefs/{D}.md")))
        hist = config.load_history()
        self.assertEqual(hist["last_brief_date"], D.isoformat())
        self.assertIn("spanish_practice", hist["rotations"])
        self.assertIsNone(fallback_brief.build_and_write(D, offline=True))


class Repo(unittest.TestCase):
    def test_example_brief_renders(self):
        import subprocess
        import sys
        out = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "brief_html.py"),
                              os.path.join(REPO, "docs", "example-brief.md"), "--format", "plain"],
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("MORNING BRIEF", out.upper())


if __name__ == "__main__":
    unittest.main()
