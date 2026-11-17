import json
import os
import sys
import unittest
from datetime import date
from zoneinfo import ZoneInfo

from _helpers import FIXTURES, TempRoot, config

import calendar_refresh
import calendar_status

AMS = ZoneInfo("Europe/Amsterdam")
DAY = date(2026, 9, 14)  # a Monday


def fixture(name):
    with open(os.path.join(FIXTURES, "calendar", f"fixture_{name}.ics"), encoding="utf-8") as f:
        return f.read()


def summaries(name, day=DAY, tz=AMS):
    events, unsupported, _ = calendar_status.build_events(fixture(name), day, tz)
    return [(e["summary"], e["start"]) for e in events], unsupported


class Expansion(unittest.TestCase):
    def test_single_event(self):
        got, _ = summaries("a_single")
        self.assertEqual(got, [("Dentist appointment", "2026-09-14T10:00:00+02:00")])

    def test_all_day(self):
        got, _ = summaries("b_allday")
        self.assertEqual(got, [("Company offsite", "2026-09-14")])

    def test_weekly_rule(self):
        self.assertEqual(summaries("c_weekly")[0], [("Book club", "2026-09-14T19:00:00+02:00")])
        self.assertEqual(summaries("c_weekly", date(2026, 9, 15))[0], [])

    def test_exdate_removes_one_occurrence(self):
        self.assertEqual(summaries("d_exdate")[0], [])
        self.assertEqual(len(summaries("d_exdate", date(2026, 9, 21))[0]), 1)

    def test_moved_occurrence(self):
        self.assertEqual(summaries("e_moved")[0], [("Book club (moved later)", "2026-09-14T20:00:00+02:00")])

    def test_utc_events_are_shown_in_local_time(self):
        # 23:00Z on Sep 14 is 01:00 on Sep 15 in Amsterdam, for single and recurring events alike.
        self.assertEqual([s for s, _ in summaries("f_utc")[0]], ["Outlook zone name"])
        got, _ = summaries("f_utc", date(2026, 9, 15))
        self.assertEqual(got, [("Late call (stored in UTC)", "2026-09-15T01:00:00+02:00"),
                               ("Weekly late sync (UTC)", "2026-09-15T01:30:00+02:00")])

    def test_unknown_tzid_falls_back_to_local_zone(self):
        got, _ = summaries("f_utc")
        self.assertEqual(got[0][1], "2026-09-14T09:00:00+02:00")

    def test_unsupported_rule_is_reported_not_guessed(self):
        got, unsupported = summaries("g_unsupported", date(2026, 1, 8))
        self.assertEqual(got, [])
        self.assertEqual(unsupported[0]["summary"], "Second Thursday meetup")

    def test_events_between_matches_single_days(self):
        days, _, _ = calendar_status.events_between(fixture("c_weekly"), date(2026, 9, 13), date(2026, 9, 22), AMS)
        self.assertEqual([d for d, evs in days.items() if evs], ["2026-09-14", "2026-09-21"])


class Refresh(TempRoot):
    def run_refresh(self, ics_name):
        path = os.path.join(FIXTURES, "calendar", f"fixture_{ics_name}.ics")
        old_argv = sys.argv
        sys.argv = ["calendar_refresh.py", "--ics", path]
        try:
            return calendar_refresh.main()
        finally:
            sys.argv = old_argv

    def test_window_is_written_once_and_then_unchanged(self):
        self.enable("calendar")
        self.assertEqual(self.run_refresh("c_weekly"), 0)
        rel = "data/calendar_window.json"
        with open(self.path(rel), encoding="utf-8") as f:
            first = json.load(f)
        self.assertIn("generated_at", first)
        self.assertEqual(sum(len(v) for v in first["days"].values()), 3)  # Mondays from this week to today+14
        os.utime(self.path(rel), (0, 0))
        self.assertEqual(self.run_refresh("c_weekly"), 0)
        self.assertEqual(os.stat(self.path(rel)).st_mtime, 0)  # unchanged content -> not rewritten

    def test_empty_feed_does_not_replace_a_full_snapshot(self):
        self.enable("calendar")
        today = config.today_local(self.cfg())
        self.write_json("data/calendar_window.json", {
            "generated_at": "2026-01-01T00:00:00+00:00", "first": "x", "last": "y",
            "days": {today.isoformat(): [{"summary": f"e{i}", "all_day": True, "start": "", "end": ""} for i in range(6)]}})
        self.assertEqual(self.run_refresh("g_unsupported"), 1)


if __name__ == "__main__":
    unittest.main()
