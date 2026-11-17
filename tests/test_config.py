import datetime
import os
import unittest

from _helpers import REPO, TempRoot, config

try:
    import yaml  # test-only cross-check; the scripts never need it
except ImportError:
    yaml = None


def plain(x):
    """PyYAML parses unquoted dates/times differently; compare as strings."""
    if isinstance(x, dict):
        return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, list):
        return [plain(v) for v in x]
    if isinstance(x, (datetime.date, datetime.datetime)):
        return x.isoformat()
    return x


class Parser(unittest.TestCase):
    def test_subset_features(self):
        text = """
# comment
a: "https://x.example/a#b"   # the # inside quotes stays
b: 'it''s'
c: plain words, with commas
d: [one, "two, three", 3]
e: {}
f:
g: ~
n: 42
x: 1.5
t: true
times: "07:30"
nested:
  enabled: false
  inner:
    enabled: true
items:
- first
- second
maps:
  - label: one
    date: "2027-01-02"
  - label: two
folded: >
  line one
  line two

  new paragraph
literal: |-
  keep
    indent
"""
        got = config.parse_yaml(text)
        self.assertEqual(got["a"], "https://x.example/a#b")
        self.assertEqual(got["b"], "it's")
        self.assertEqual(got["c"], "plain words, with commas")
        self.assertEqual(got["d"], ["one", "two, three", 3])
        self.assertEqual((got["e"], got["f"], got["g"]), ({}, None, None))
        self.assertEqual((got["n"], got["x"], got["t"]), (42, 1.5, True))
        self.assertEqual(got["nested"], {"enabled": False, "inner": {"enabled": True}})
        self.assertEqual(got["items"], ["first", "second"])
        self.assertEqual(got["maps"], [{"label": "one", "date": "2027-01-02"}, {"label": "two"}])
        self.assertEqual(got["folded"], "line one line two\nnew paragraph\n")
        self.assertEqual(got["literal"], "keep\n  indent")

    def test_unquoted_times_and_dates_stay_strings(self):
        got = config.parse_yaml("t: 07:30\nd: 2026-11-16\nyes: yes\n")
        self.assertEqual(got, {"t": "07:30", "d": "2026-11-16", "yes": "yes"})

    def test_errors_carry_line_numbers(self):
        cases = {
            "a: b: c\n": 1,
            "a: 1\na: 2\n": 2,
            "a:\n\tb: 1\n": 2,
            "a: x\n  y\n": 2,
            'a: "open\n': 1,
            "a: &anchor 1\n": 1,
            "a:\n  - x\n  y: 1\n": 3,
            "just text\n": 1,
        }
        for text, line in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(config.ConfigError) as cm:
                    config.parse_yaml(text)
                self.assertEqual(cm.exception.line, line)

    def test_shipped_profile_parses(self):
        with open(os.path.join(REPO, "config", "profile.yaml"), encoding="utf-8") as f:
            cfg = config.parse_yaml(f.read())
        self.assertEqual(config.get(cfg, "user.timezone"), "Europe/Lisbon")
        self.assertTrue(config.enabled(cfg, "countdowns"))
        self.assertFalse(config.enabled(cfg, "telegram"))

    @unittest.skipUnless(yaml, "PyYAML not installed")
    def test_matches_pyyaml_on_shipped_profile(self):
        with open(os.path.join(REPO, "config", "profile.yaml"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(config.parse_yaml(text), plain(yaml.safe_load(text)))


class Helpers(TempRoot):
    def test_get_enabled_and_defaults(self):
        cfg = {"a": {"b": {"c": 1}, "enabled": "true"}, "n": None}
        self.assertEqual(config.get(cfg, "a.b.c"), 1)
        self.assertEqual(config.get(cfg, "a.x", "d"), "d")
        self.assertEqual(config.get(cfg, "n", "d"), "d")
        self.assertFalse(config.enabled(cfg, "a"))  # only a real boolean true counts

    def test_bad_timezone_falls_back_to_utc(self):
        self.assertEqual(config.tz({"user": {"timezone": "Mars/Base"}}).key, "UTC")

    def test_split_link_and_dates(self):
        self.assertEqual(config.split_link("Yoga flow | https://x.example/v?a=1"), ("Yoga flow", "https://x.example/v?a=1"))
        self.assertEqual(config.split_link("No link here"), ("No link here", None))
        d = datetime.date(2026, 11, 16)
        self.assertEqual(config.pretty_date(d), "Monday, November 16, 2026")
        self.assertEqual(config.short_date(d), "Nov 16")

    def test_root_override_is_used(self):
        self.assertEqual(config.path("state/history.json"), os.path.join(self.root, "state", "history.json"))
        hist = config.load_history()
        hist["x"] = 1
        config.save_history(hist)
        self.assertEqual(config.load_history()["x"], 1)


if __name__ == "__main__":
    unittest.main()
