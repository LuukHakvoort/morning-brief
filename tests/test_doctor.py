import os
import subprocess
import sys

from _helpers import REPO, TempRoot

DOCTOR = os.path.join(REPO, "scripts", "doctor.py")


class Doctor(TempRoot):
    def run_doctor(self, *args):
        env = dict(os.environ, MORNING_BRIEF_ROOT=self.root)
        return subprocess.run([sys.executable, DOCTOR, *args], capture_output=True, text=True, env=env)

    def test_shipped_config_has_no_errors(self):
        out = self.run_doctor("--ci")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("0 error(s)", out.stdout)

    def test_a_typo_is_reported_with_its_line(self):
        self.edit_profile('  timezone: "Europe/Lisbon"', "  timezone: Europe/Lisbon: oops")
        out = self.run_doctor("--ci")
        self.assertEqual(out.returncode, 1)
        self.assertIn("line ", out.stdout)

    def test_bad_values_are_errors(self):
        self.edit_profile('timezone: "Europe/Lisbon"', 'timezone: "Europe/Atlantis"')
        self.edit_profile('time_local: "07:30"', 'time_local: "7.30"')
        out = self.run_doctor("--ci")
        self.assertEqual(out.returncode, 1)
        self.assertIn("user.timezone", out.stdout)
        self.assertIn("delivery.time_local", out.stdout)

    def test_template_values_are_flagged_outside_ci(self):
        out = self.run_doctor()
        self.assertIn("user.name is still the template's example", out.stdout)
        self.assertIn("cron:", out.stdout)
