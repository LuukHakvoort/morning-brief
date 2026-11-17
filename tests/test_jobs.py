import json
from datetime import date

from _helpers import TempRoot

import facts
from modules import jobs

D = date(2026, 11, 16)
HEADER = "org,role,location,deadline,url,priority,status,pay,applied_on,notes\n"


class Jobs(TempRoot):
    def setUp(self):
        super().setUp()
        self.enable("jobs")

    def csv(self, rows, bom=True):
        self.write_text("data/jobs.csv", ("﻿" if bom else "") + HEADER + "".join(r + "\n" for r in rows))

    def facts(self, day=D):
        return facts.build(self.cfg(), day, history={})

    def test_ordering_and_filters(self):
        self.csv([
            "Late Co,Analyst,,2026-12-30,,2,open,ok,,",
            "Urgent Co,Analyst,,2026-11-20,,2,open,ok,,",
            "Top Co,Lead,,,,1,open,ok,,",
            "Unpaid Co,Intern,,,,1,open,unpaid,,",
            "Gone Co,Analyst,,2026-11-01,,1,open,ok,,",
            "Closed Co,Analyst,,,,1,closed,ok,,",
            "Watch Co,Fellow,,,,1,watch,ok,,",
            "Applied Co,Analyst,,,,1,applied,ok,2026-11-06,",
        ])
        f, _ = self.facts()
        j = f["jobs"]
        self.assertEqual([c["org"] for c in j["todays_picks"]], ["Top Co", "Urgent Co", "Late Co"])
        self.assertEqual([c["org"] for c in j["watchlist"]], ["Watch Co"])
        self.assertEqual([c["org"] for c in j["follow_ups"]], ["Applied Co"])
        self.assertEqual(j["pipeline_remaining"], 0)
        self.assertTrue(j["needs_refill"])

    def test_picks_are_stable_on_the_same_day_and_not_repeated(self):
        self.csv([f"Org {i},Role,,,,2,open,ok,," for i in range(7)])
        f, ctx = self.facts()
        first = [c["key"] for c in f["jobs"]["todays_picks"]]
        facts.save(ctx)
        again, _ = self.facts()
        self.assertEqual([c["key"] for c in again["jobs"]["todays_picks"]], first)
        tomorrow, _ = self.facts(date(2026, 11, 17))
        self.assertFalse(set(first) & {c["key"] for c in tomorrow["jobs"]["todays_picks"]})
        self.assertEqual(tomorrow["jobs"]["pipeline_remaining"], 1)

    def test_closing_this_week_and_web_found_roles(self):
        self.csv(["Mine,Analyst,,2026-11-19,,3,open,ok,,"], bom=False)
        self.write_json("state/job_pipeline.json", {"items": [
            {"org": "Found", "role": "Researcher", "deadline": "2026-11-18", "priority": 1, "url": "https://x.example"}],
            "served": [{"key": "mine — analyst", "date": "2026-11-10"}]})
        f, _ = self.facts()
        self.assertEqual([c["org"] for c in f["jobs"]["todays_picks"]], ["Found"])
        self.assertEqual([(c["org"], c["suggested_on"]) for c in f["jobs"]["closing_7d"]], [("Mine", "2026-11-10")])

    def test_serve_is_idempotent_and_prunes(self):
        self.write_json("state/job_pipeline.json", {"items": [{"org": "Old", "role": "R", "deadline": "2026-10-01"}],
                                                    "served": [{"key": "ancient", "date": "2026-01-01"}]})
        jobs.serve(self.cfg(), D, ["A — B", "a — b"])
        jobs.serve(self.cfg(), D, ["a — b"])
        with open(self.path("state/job_pipeline.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["served"], [{"key": "a — b", "date": "2026-11-16"}])
        self.assertEqual(data["items"], [])

    def test_missing_csv_is_a_warning_not_a_crash(self):
        import os
        os.remove(self.path("data/jobs.csv"))
        f, _ = self.facts()
        self.assertEqual(f["jobs"]["todays_picks"], [])
        self.assertTrue(any("jobs.csv" in w for w in f["warnings"]))
