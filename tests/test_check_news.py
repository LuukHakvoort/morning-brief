import unittest
from datetime import date

from _helpers import TempRoot

import check_news

D = date(2026, 11, 16)


class Freshness(unittest.TestCase):
    def test_dates_in_text_and_urls(self):
        self.assertEqual(check_news.item_is_fresh("**Headline · Nov 14 · BBC**: x", D, 7), (True, ""))
        self.assertFalse(check_news.item_is_fresh("**Headline · Nov 1 · BBC**: x", D, 7)[0])
        self.assertTrue(check_news.item_is_fresh("x https://n.example/2026/11/15/story", D, 7)[0])
        self.assertFalse(check_news.item_is_fresh("undated https://n.example/story", D, 7)[0])

    def test_month_only_url_from_another_month_is_stale(self):
        self.assertFalse(check_news.item_is_fresh("x https://n.example/2026/10/story", D, 7)[0])
        self.assertTrue(check_news.item_is_fresh("x https://n.example/2026/11/story", D, 7)[0])


class Checker(TempRoot):
    def brief(self, day, bullets, heading="World pulse"):
        body = "\n".join(bullets)
        self.write_text(f"briefs/{day}.md", f"# Morning Brief — x\n\nHi.\n\n## {heading}\n\n{body}\n\n## Closing kick\n\nGo.\n")
        return self.path(f"briefs/{day}.md")

    def test_ok_and_heads_up_bullets_are_skipped(self):
        path = self.brief("2026-11-16", ["- **Headline · Nov 15 · BBC**: x ([link](https://n.example/a))",
                                          "- Heads up: fewer fresh headlines today than usual."])
        result = check_news.check_brief(path)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["bullets"], 1)

    def test_missing_link_and_repeat_are_flagged(self):
        self.brief("2026-11-14", ["- **Headline · Nov 13 · BBC**: old ([link](https://n.example/a?utm=1))"])
        path = self.brief("2026-11-16", ["- **Headline · Nov 15 · BBC**: same story ([link](https://n.example/a/))",
                                          "- **Report · Nov 15 · OECD**: no link"])
        problems = [p["problem"] for p in check_news.check_brief(path)["problems"]]
        self.assertTrue(any("repeats" in p for p in problems), problems)
        self.assertIn("no source link", problems)

    def test_custom_heading(self):
        path = self.brief("2026-11-16", ["- **Headline · Nov 15 · BBC**: x"], heading="News")
        self.assertEqual(check_news.check_brief(path, heading="News")["bullets"], 1)
        self.assertEqual(check_news.check_brief(path)["bullets"], 0)


if __name__ == "__main__":
    unittest.main()
