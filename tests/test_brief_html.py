import os
import subprocess
import sys
import tempfile
import unittest

from _helpers import REPO

import brief_html

BRIEF = """# Morning Brief — Monday, November 16, 2026

Let's go, Alex! Today's lever: the report.

## Countdown

Countdown check: **12 days** to the half marathon (Sat Nov 28).

## My Custom Section

Fish & chips for <lunch>.

- one [link](https://x.example/a?b=1&c=2)
- **bold** and *italic*

## World pulse

- **Headline · Nov 15 · BBC**: something ([link](https://n.example/2026/11/15/x))
"""


def render(fmt):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(BRIEF)
    try:
        return subprocess.run([sys.executable, os.path.join(REPO, "scripts", "brief_html.py"), f.name, "--format", fmt],
                              capture_output=True, text=True, check=True).stdout
    finally:
        os.unlink(f.name)


class Render(unittest.TestCase):
    def test_parse(self):
        title, lede, sections = brief_html.parse_brief(BRIEF)
        self.assertEqual(title, "Morning Brief — Monday, November 16, 2026")
        self.assertTrue(lede.startswith("Let's go"))
        self.assertEqual([s["heading"] for s in sections], ["Countdown", "My Custom Section", "World pulse"])

    def test_html_escapes_text_and_keeps_markup(self):
        out = render("html")
        self.assertIn("Fish &amp; chips for &lt;lunch&gt;", out)
        self.assertIn('href="https://x.example/a?b=1&amp;c=2"', out)
        self.assertIn("<strong>bold</strong>", out)
        self.assertIn("<em>italic</em>", out)
        self.assertIn(">12<", out.replace(" ", ""))  # the countdown number gets the stat treatment
        self.assertIn("MY CUSTOM SECTION", out.upper())

    def test_artifact_and_plain(self):
        self.assertNotIn("<!DOCTYPE", render("artifact"))
        plain = render("plain")
        self.assertIn("one link — https://x.example/a?b=1&c=2", plain)
        self.assertNotIn("**", plain)


if __name__ == "__main__":
    unittest.main()
