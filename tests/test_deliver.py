"""Which channels go out, and when. Every sender is replaced by a fake."""

import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from _helpers import TempRoot, config

import deliver

LIS = ZoneInfo("Europe/Lisbon")
ISO = "2026-11-16"
PUSH_TIME = datetime(2026, 11, 16, 7, 50, tzinfo=LIS)
LATER = datetime(2026, 11, 16, 10, 17, tzinfo=LIS)
BRIEF = "# Morning Brief — Monday, November 16, 2026\n\nLet's go.\n\n## World pulse\n\n- item\n"


class Gating(TempRoot):
    def setUp(self):
        super().setUp()
        self.enable("telegram", "email")
        self.sent, self.fail, self.alerts, self.builds = [], set(), [], 0

        def fake(name):
            def send(*_a, **_k):
                if name in self.fail:
                    raise RuntimeError(f"{name} down")
                self.sent.append(name)
            return send

        def fake_build(today, force=False, offline=False):
            self.builds += 1
            self.write_text(f"briefs/{ISO}.md", "# Morning Brief — Monday, November 16, 2026\n\n*Backup edition: x*\n")
            return "backup teaser"

        patches = {"deliver_telegram": fake("telegram"), "deliver_email": fake("email"),
                   "build_and_write": fake_build,
                   "alert_once": lambda cfg, iso, text, force=False: self.alerts.append(text)}
        self.saved = {k: getattr(deliver, k) for k in patches}
        for k, v in patches.items():
            setattr(deliver, k, v)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(deliver, k, v)
        super().tearDown()

    def run_(self, now, event, force=False):
        return deliver.run(self.cfg(), now, event, force)

    def test_push_sends_both_and_records_both(self):
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.assertEqual(self.run_(PUSH_TIME, "push"), 0)
        self.assertEqual(self.sent, ["telegram", "email"])
        hist = config.load_history()
        self.assertEqual((hist["telegram_last_sent_date"], hist["email_last_sent_date"]), (ISO, ISO))

    def test_repeat_runs_send_nothing(self):
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.run_(PUSH_TIME, "push")
        self.sent.clear()
        self.assertEqual(self.run_(PUSH_TIME, "push"), 0)
        self.assertEqual(self.run_(LATER, "schedule"), 0)
        self.assertEqual(self.sent, [])

    def test_only_the_failed_channel_is_retried(self):
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.fail = {"email"}
        self.assertEqual(self.run_(PUSH_TIME, "push"), 1)
        self.assertEqual((self.sent, len(self.alerts)), (["telegram"], 1))
        self.assertIsNone(config.load_history().get("email_last_sent_date"))
        self.fail, self.sent = set(), []
        self.assertEqual(self.run_(LATER, "schedule"), 0)
        self.assertEqual(self.sent, ["email"])

    def test_force_resends_everything(self):
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.run_(PUSH_TIME, "push")
        self.sent.clear()
        self.assertEqual(self.run_(PUSH_TIME, "workflow_dispatch", force=True), 0)
        self.assertEqual(self.sent, ["telegram", "email"])

    def test_disabled_channel_is_skipped(self):
        self.edit_profile("email:\n  enabled: true", "email:\n  enabled: false")
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.run_(PUSH_TIME, "push")
        self.assertEqual(self.sent, ["telegram"])

    def test_no_channels_means_no_op(self):
        self.edit_profile("email:\n  enabled: true", "email:\n  enabled: false")
        self.edit_profile("telegram:\n  enabled: true", "telegram:\n  enabled: false")
        self.assertEqual(self.run_(LATER, "schedule"), 0)
        self.assertEqual((self.sent, self.builds), ([], 0))

    def test_schedule_without_brief_builds_the_backup(self):
        self.assertEqual(self.run_(LATER, "schedule"), 0)
        self.assertEqual((self.builds, self.sent), (1, ["telegram", "email"]))

    def test_push_without_brief_does_nothing(self):
        self.assertEqual(self.run_(PUSH_TIME, "push"), 0)
        self.assertEqual((self.sent, self.builds), ([], 0))

    def test_schedule_outside_the_backup_window_is_skipped(self):
        for t in (datetime(2026, 11, 16, 8, 17, tzinfo=LIS), datetime(2026, 11, 16, 19, 17, tzinfo=LIS)):
            self.assertEqual(self.run_(t, "schedule"), 0)
        self.assertEqual((self.sent, self.builds), ([], 0))

    def test_missing_secret_fails_the_channel(self):
        deliver.deliver_email = self.saved["deliver_email"]  # the real one, which checks the secret
        os.environ.pop("SMTP_PASSWORD", None)
        self.write_text(f"briefs/{ISO}.md", BRIEF)
        self.assertEqual(self.run_(PUSH_TIME, "push"), 1)
        self.assertEqual(self.sent, ["telegram"])
        self.assertIn("SMTP_PASSWORD", self.alerts[0])


class Messages(TempRoot):
    def test_email_is_multipart_html_with_a_dated_subject(self):
        self.write_text(f"briefs/{ISO}.md", BRIEF.replace("Let's go.", "Let's go & win <today>."))
        msg = deliver.build_email(self.cfg(), self.path(f"briefs/{ISO}.md"), "November 16, 2026", "me@example.com")
        self.assertEqual(msg.get_content_type(), "multipart/alternative")
        self.assertEqual(msg["Subject"], "Morning Brief — November 16, 2026")
        html = msg.get_body(("html",)).get_content()
        self.assertIn("&amp; win &lt;today&gt;", html)

    def test_title_date_works_for_any_title(self):
        self.assertEqual(deliver.title_date("# Daily Kick-off — Friday, March 5, 2027\n", "x"), "March 5, 2027")
        self.assertEqual(deliver.title_date("no title", "fallback"), "fallback")

    def test_telegram_chunks_respect_the_limit(self):
        text = "# T\n\n" + "\n\n".join(f"## S{i}\n\n" + "word " * 300 for i in range(10))
        chunks = deliver.telegram_chunks(text, limit=1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertGreater(len(chunks), 10)


if __name__ == "__main__":
    unittest.main()
