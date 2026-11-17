# Morning brief

This repo generates a personal morning brief every day. A Claude Code cloud
routine runs the steps below on a schedule; GitHub Actions then delivers
the result by Telegram and email (`.github/workflows/deliver.yml`). If the
routine produces nothing (for example, Claude's usage limit was reached),
the same workflow builds a simpler no-AI "backup edition" later in the
morning.

If you were invoked to **run the morning brief**, follow this exact
sequence. For anything else in this repo (editing config, debugging a
script), just do the normal thing; see README.md for how it all fits.

1. **Read** `config/profile.yaml` (the facts about the reader) and
   `config/brief_composition.md` (voice, structure, rules) in full. They are
   the source of truth.

2. **Gather facts:** `python3 scripts/facts.py`. Its `today` is the date
   everywhere below (it is in `user.timezone`, not the server's). It only
   contains keys for the modules enabled in profile.yaml. If it prints an
   `error`, the profile has a mistake at the given line: write a short brief
   that says so (heads-up line), and still do steps 8-10. Don't fetch the
   calendar yourself: `facts.calendar` comes from a snapshot that a GitHub
   workflow refreshes, because this sandbox can't reach calendar hosts.

   If `briefs/<today>.md` already exists and contains the line
   "Backup edition:", that's the automatic backup: overwrite it with the
   full brief and carry on as normal.

3. **Weekly extras and refills:** if `is_weekly_extras_day`, do the weekly
   work in brief_composition.md. If `jobs.needs_refill` (or there are no
   picks), refill the job pipeline as described there, then run
   `python3 scripts/facts.py` again.

4. **News:** web-search `news.topics` for the last `news.max_age_days`
   days. Put the date range in the query (e.g. "week of 9-16 November
   2026") and only use results whose date you can verify.

5. **Compose** the brief in Markdown per brief_composition.md and save it
   as `briefs/<today>.md`. Then run `python3 scripts/check_news.py
   briefs/<today>.md`. If it reports problems (exit code 1), replace those
   bullets with fresh, dated items and re-run it, up to 2 times. If
   problems remain, delete the flagged bullets and add
   `- Heads up: fewer fresh headlines today than usual.` A `checker_error`
   in its output doesn't block anything.

6. **Persistent page** (only if `artifact.enabled`):
   a. `python3 scripts/brief_html.py briefs/<today>.md --format artifact`
      gives the page content.
   b. If `state/history.json` `artifact.url` is null, publish a new
      artifact titled `"<artifact.title_prefix> — <date_pretty>"` and record
      its URL in `artifact.url` and today in `artifact.last_published_date`.
   c. Otherwise read that exact URL first (publishing to an artifact this
      session hasn't read is refused), then publish to the same URL so it
      updates in place, and set `artifact.last_published_date`.
   d. If this fails, note it in your final message and continue.

7. **Record state:** `python3 scripts/facts.py --save` (or
   `--save --serve-jobs KEY …` if you swapped a job pick). Don't edit
   `rotations`, `running` or the `*_last_sent_date` keys of
   `state/history.json` by hand.

8. **Notify:** `PushNotification` with a one-line, plain-text teaser (no
   Markdown, no tags), status `"proactive"`; then `SendUserFile` with the
   brief file, status `"proactive"`. **Don't send email or Telegram
   yourself**, even if a tool for it is available: GitHub Actions does that
   when your push lands, from the file itself.

9. **Commit and push** to `main`: `git add briefs state data`, commit as
   `Morning brief <today>`, `git push`. This is what triggers delivery, and
   each run starts from a fresh clone, so anything not pushed is lost. If
   the push is rejected, `git pull --rebase` once and push again; if it
   still fails, say so in your final message.

10. **Your final message is the brief itself**, verbatim, as Markdown, not a
    summary of what you did. Each run is its own session, so opening the
    notification lands on this transcript. Add any failure notes (artifact,
    push) after the brief.
