"""Shared test setup: every test works in a temporary copy of config/, data/ and state/."""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
sys.path.insert(0, os.path.join(REPO, "scripts"))

import config  # noqa: E402


class TempRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        for d in ("config", "data", "state"):
            shutil.copytree(os.path.join(REPO, d), os.path.join(self.root, d))
        os.makedirs(os.path.join(self.root, "briefs"))
        self._old_root = os.environ.get("MORNING_BRIEF_ROOT")
        os.environ["MORNING_BRIEF_ROOT"] = self.root

    def tearDown(self):
        if self._old_root is None:
            os.environ.pop("MORNING_BRIEF_ROOT", None)
        else:
            os.environ["MORNING_BRIEF_ROOT"] = self._old_root
        self._tmp.cleanup()

    # --- helpers
    def path(self, rel):
        return os.path.join(self.root, rel)

    def profile_text(self):
        with open(self.path("config/profile.yaml"), encoding="utf-8") as f:
            return f.read()

    def edit_profile(self, old, new):
        text = self.profile_text()
        self.assertIn(old, text, f"test setup: {old!r} not in profile.yaml")
        with open(self.path("config/profile.yaml"), "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))

    def enable(self, *sections):
        text = self.profile_text()
        for name in sections:
            text, n = re.subn(rf"(^{name}:\n(?:[ #].*\n|\n)*?\s+enabled:) false", r"\1 true", text, count=1, flags=re.M)
            self.assertEqual(n, 1, f"test setup: couldn't enable {name}")
        with open(self.path("config/profile.yaml"), "w", encoding="utf-8") as f:
            f.write(text)

    def write_json(self, rel, data):
        with open(self.path(rel), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def write_text(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as f:
            f.write(text)

    def cfg(self):
        return config.load_profile()
