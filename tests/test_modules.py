from datetime import date

from _helpers import TempRoot, config

import facts

MON = date(2026, 11, 16)


def ev(summary, start, end, all_day=False):
    return {"summary": summary, "location": None, "all_day": all_day, "start": start, "end": end}


class Modules(TempRoot):
    def setUp(self):
        super().setUp()
        self.write_json("data/trips.json", {
            "trips": [{"name": "Conf", "city": "Berlin", "start": "2026-11-18", "end": "2026-11-19",
                       "arrive": "11:40", "sessions": [{"date": "2026-11-18", "when": "10:00", "title": "Keynote", "place": "Hall A"},
                                                       {"date": "2026-11-18", "when": "14:00", "title": "Workshop"}]}],
            "away": [{"place": "family visit", "start": "2026-11-28", "end": "2026-11-29"}],
            "prep_schedule": [{"days_before": 2, "task": "{city}: read up on {titles}."},
                              {"days_after": 1, "task": "{city} follow-up."}]})

    def build(self, day=MON, history=None):
        return facts.build(self.cfg(), day, history={} if history is None else history)

    def test_trips_location_tasks_and_skipped_items(self):
        self.enable("trips")
        f, _ = self.build()
        self.assertEqual(f["trips"]["tasks_today"][0]["task"], "Berlin: read up on Keynote, Workshop.")
        self.assertEqual(f["location"], "Lisbon")
        wed, _ = self.build(date(2026, 11, 18))
        self.assertTrue(wed["away"])
        self.assertEqual(wed["trips"]["trip_today"]["day"], 1)
        self.assertEqual(len(wed["trips"]["trip_today"]["sessions"]), 2)
        self.assertEqual(wed["skipped_while_away"], ["Football with friends"])
        thu, _ = self.build(date(2026, 11, 19))
        self.assertEqual([i["name"] for i in thu["fixed_items_today"]], ["Online Spanish class"])  # away_ok
        fri, _ = self.build(date(2026, 11, 20))
        self.assertEqual(fri["trips"]["tasks_today"][0]["task"], "Berlin follow-up.")

    def test_countdowns_with_reminders_and_trips(self):
        self.enable("trips")
        self.edit_profile('date: "2027-09-26"', 'date: "2026-11-30"')
        f, _ = self.build()
        cd = f["countdowns"]
        self.assertEqual(cd["next"], {"label": "your Berlin trip", "date": "2026-11-18", "days": 2})
        self.assertEqual(cd["reminders_today"], [{"label": "the half marathon", "text": "Book the hotel near the start line"}])
        self.assertEqual([c["label"] for c in cd["upcoming"]], ["your Berlin trip", "the half marathon"])

    def test_past_countdowns_are_ignored(self):
        self.edit_profile('date: "2027-09-26"', 'date: "2026-01-01"')
        f, _ = self.build()
        self.assertIsNone(f["countdowns"]["next"])

    def test_rotations_advance_daily_and_repeat_within_a_day(self):
        f, ctx = self.build()
        self.assertEqual([r["index"] for r in f["rotations"]], [0, 0])
        facts.save(ctx)
        hist = config.load_history()
        again, _ = self.build(MON, hist)
        self.assertEqual([r["index"] for r in again["rotations"]], [0, 0])
        tue, ctx = self.build(date(2026, 11, 17), hist)
        self.assertEqual([r["index"] for r in tue["rotations"]], [1, 1])
        facts.save(ctx)
        wed, _ = self.build(date(2026, 11, 18), config.load_history())
        self.assertEqual([r["index"] for r in wed["rotations"]], [2, 0])  # "Reading" has 2 items
        self.assertEqual(wed["workout"]["today"]["text"], "Bodyweight strength: squats, push-ups, lunges, glute bridges (3 rounds)")

    def test_run_plan_avoids_busy_evenings_and_travel_and_stays_stable(self):
        self.enable("trips", "calendar")
        self.edit_profile("  runs:\n    enabled: false", "  runs:\n    enabled: true")
        self.write_json("data/calendar_window.json", {
            "generated_at": config.now_local(self.cfg()).isoformat(), "first": "2026-11-16", "last": "2026-11-30",
            "days": {"2026-11-17": [ev("Dinner", "2026-11-17T19:00:00+00:00", "2026-11-17T21:00:00+00:00")],
                     "2026-11-21": [ev("Wedding", "2026-11-21", "2026-11-22", all_day=True)]}})
        f, ctx = self.build()
        runs = f["workout"]["runs"]
        blocked = runs["blocked_this_week"]
        for day in ("2026-11-17", "2026-11-18", "2026-11-19", "2026-11-21"):
            self.assertIn(day, blocked)
        self.assertNotIn("2026-11-16", blocked)
        dates = [r["date"] for r in runs["plan"]]
        self.assertEqual(len(dates), 2)
        self.assertFalse(set(dates) & set(blocked))
        self.assertEqual({r["type"] for r in runs["plan"]}, {"easy", "long"})
        facts.save(ctx)
        later, _ = self.build(date(2026, 11, 20), config.load_history())
        self.assertEqual([r["date"] for r in later["workout"]["runs"]["plan"]], dates)

    def test_calendar_hide_patterns_and_staleness(self):
        self.enable("calendar")
        self.edit_profile("hide_patterns: []", 'hide_patterns: ["focus time"]')
        self.write_json("data/calendar_window.json", {
            "generated_at": "2026-11-01T05:00:00+00:00", "first": "2026-11-16", "last": "2026-11-30",
            "days": {"2026-11-16": [ev("Focus time", "2026-11-16T09:00:00+00:00", "2026-11-16T11:00:00+00:00"),
                                    ev("Team sync", "2026-11-16T11:00:00+00:00", "2026-11-16T11:30:00+00:00")]}})
        f, _ = self.build()
        self.assertEqual([e["summary"] for e in f["calendar"]["events_today"]], ["Team sync"])
        self.assertTrue(any("days old" in w for w in f["warnings"]))

    def test_broken_module_becomes_a_warning(self):
        self.enable("trips")
        self.write_text("data/trips.json", "{not json")
        f, _ = self.build()
        self.assertIn("trips", f)
        self.assertTrue(any("trips.json" in w for w in f["warnings"]))
