# morning-brief

A personal morning brief, written for you every day by Claude and delivered
to your phone and inbox before you're out of bed.

Each morning a [Claude Code](https://claude.com/claude-code) cloud routine
reads your profile, your calendar and your plans, searches the week's news,
and writes a short, coach-toned brief: today's one big lever, your
countdowns, today's shape, a few curated headlines, and a first move for
the next 30 minutes. GitHub Actions then sends it by **email** and
**Telegram**. If Claude can't run one morning, a free no-AI **backup
edition** goes out instead, so a brief always arrives.

```
# Morning Brief — Monday, November 16, 2026

Let's go, Alex! Today's lever: the first draft of the project report,
before lunch, while the head is fresh.

## Countdown
Countdown check: 14 days to the half marathon (Mon Nov 30).
...
```

See [docs/example-brief.md](docs/example-brief.md) for a full example.

## What you get

- **Core**, always on: today's focus and schedule changes, recurring weekly
  items, your calendar (iCloud, Google, Outlook… any ICS link), daily
  rotations (language practice, reading… whatever you list), and news.
- **Optional modules**, switched on in `config/profile.yaml`:
  - **countdowns**: dates you're working towards, with reminders on the way
  - **trips**: where you are each day, the agenda, prep and follow-up tasks
  - **workout**: a daily short workout, plus an optional weekly run plan that
    avoids your busy evenings
  - **jobs**: today's applications from your own list (a CSV), topped up
    with roles Claude finds online
- **Delivery**: email (styled HTML), Telegram, a phone notification from
  the Claude app, and optionally a persistent web page (a Claude artifact)
  that updates in place every morning.

You change what the brief says and how it sounds by editing two files, not
code: `config/profile.yaml` (facts) and `config/brief_composition.md`
(voice and structure). Adding a section of your own is a paragraph of
plain English in the composition file.

## What it costs

- **Claude:** a plan that includes Claude Code cloud routines. Each
  morning's run uses some of your plan's usage, so on a day your limit is
  reached, the free backup edition stands in.
- **GitHub:** free. Use a **private** repository (see Privacy). With the
  default schedules the workflows use about 1,000 of the 2,000 free Actions
  minutes a private repo gets per month on GitHub Free; `doctor.py` suggests
  a narrower schedule that roughly halves that.
- **Telegram and email:** free.

## How it works

```
 every 3 h        calendar-refresh.yml ── your ICS link (secret) ──> data/calendar_window.json
                                                                          │
 07:30 local      Claude routine (cloud) ── follows CLAUDE.md             │
                    1. scripts/facts.py  <── profile.yaml, data/, state/ ─┘
                    2. web search: news (+ weekly research)
                    3. writes briefs/<date>.md, checks the news, saves state
                    4. phone notification (+ artifact page)
                    5. git push ─────────────┐
                                             ▼
 seconds later    deliver.yml ── scripts/deliver.py ──> email + Telegram
 hourly           deliver.yml ── no brief by backup_after? build the backup edition, send it
```

Claude's cloud sandbox can't reach calendar servers, and a model is the
wrong tool for copying a 30 KB HTML email into a tool call. So everything
that needs plain network access or exact bytes (calendar fetch, email,
Telegram) runs in GitHub Actions, and the routine only writes Markdown and
pushes it.

| State in `state/history.json` | Written by |
|---|---|
| `last_brief_date`, `rotations`, `running` | `scripts/facts.py --save` (the routine, or the backup edition) |
| `artifact` | the routine (if the artifact page is enabled) |
| `telegram_last_sent_date`, `email_last_sent_date`, `alert_last_sent_date` | `scripts/deliver.py` (GitHub Actions) only |

`state/job_pipeline.json` holds jobs found online and the ones already
suggested, so no role is suggested twice.

## Set it up

You need a GitHub account, a Claude plan with Claude Code, and about 30
minutes. Steps 4-6 are only for the channels you want.

1. **Create your copy.** Click **Use this template → Create a new
   repository** and choose **Private**. Clone it.

2. **Fill in your profile.** Edit `config/profile.yaml`: your name,
   timezone, the time you want the brief, recurring items, rotations, news
   topics, and which modules to enable. Then look through
   `config/brief_composition.md`; the `Customize:` blocks are the places
   most people change. Check your work:

   ```
   python3 scripts/doctor.py
   python3 scripts/facts.py              # what the brief will know today
   python3 scripts/fallback_brief.py --dry-run --offline    # a sample brief, no AI
   ```

   Python 3.9+ is all you need; there's nothing to install.

3. **Turn the workflows on.** In your repo: **Settings → Secrets and
   variables → Actions → Variables → New repository variable**:
   `MORNING_BRIEF_ENABLED` = `true`. Also check **Settings → Actions →
   General → Workflow permissions** is set to **Read and write
   permissions**, so the workflows can commit.

4. **Email** (optional): set `email.enabled: true` and `email.to` in the
   profile, then add the secret `SMTP_PASSWORD`. For Gmail, that's an
   [app password](https://myaccount.google.com/apppasswords) (it needs
   2-Step Verification on the account); the email is sent from the same
   address it goes to. For other providers, set `email.smtp_host` /
   `smtp_port`, and add `SMTP_USERNAME` if your login differs from `email.to`.

5. **Telegram** (optional): set `telegram.enabled: true`. Create a bot by
   messaging [@BotFather](https://t.me/BotFather) (`/newbot`) and add its
   token as the secret `TELEGRAM_BOT_TOKEN`. Send your bot any message, open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, and add the number at
   `"chat":{"id":…}` as the secret `TELEGRAM_CHAT_ID`.

6. **Calendar** (optional): set `calendar.enabled: true` and add your
   calendar's ICS link as the secret `CALENDAR_ICS_URL`:
   - **Google Calendar:** Settings → your calendar → *Integrate calendar* →
     *Secret address in iCal format*.
   - **iCloud:** Calendar app → right-click the calendar → *Share Calendar*
     → *Public Calendar* → copy the link (`webcal://…` is fine).
   - **Outlook:** Settings → Calendar → Shared calendars → *Publish a
     calendar* → the ICS link.

   Then run **Actions → Refresh the calendar → Run workflow** once and
   check that `data/calendar_window.json` appeared.

7. **Commit and push** your profile changes.

8. **Create the routine.** In Claude Code, in your clone, run `/schedule`
   and ask for a daily routine on this repository:
   - **Prompt:** `Run the morning brief: follow CLAUDE.md in this repo exactly, step by step.`
   - **Schedule:** the UTC cron line `doctor.py` printed for your
     `delivery.time_local` (routine schedules are in UTC).
   - **Tools:** Bash, Read, Write, Edit, Glob, Grep, WebSearch,
     PushNotification, SendUserFile, plus Artifact if you enabled the page.
     No connectors are needed.
   - It must be able to push to `main`: that push is what sends the email
     and Telegram message.

   You can manage it later at [claude.ai/code/routines](https://claude.ai/code/routines),
   or ask Claude to list or update it.

9. **Try it.** Run the routine once by hand. Within a minute or two of its
   push you should get the email and the Telegram message. To test delivery
   on its own, run **Actions → Deliver the brief → Run workflow** with
   *force* ticked.

## Day to day

- **Change anything** by editing `config/profile.yaml` or
  `config/brief_composition.md` (on github.com is fine), or just ask Claude
  in your clone: "add a rotation for guitar practice", "make the tone calmer".
- **Plan a day:** add a focus or a schedule change to `data/day_plan.json`.
- **Trips:** add them to `data/trips.json`. **Jobs:** edit `data/jobs.csv`
  in any spreadsheet app.
- **Past briefs** are in `briefs/`; `python3 scripts/brief_cli.py list` /
  `show 2026-11-16` reads them in the terminal.
- **Resend today's brief:** Actions → Deliver the brief → Run workflow →
  *force*.

## Customizing

- **A new section that needs live information** (sports fixtures, local
  events, the weather): describe it in `config/brief_composition.md` where
  the `Customize:` block suggests. The routine web-searches for it.
- **A new daily habit:** add a list under `rotations:` in the profile.
- **A new module** that needs code: write `scripts/modules/<name>.py` with
  a `facts(ctx)` function (and optionally `save(ctx, result, hist)`), add it
  to `REGISTRY` in `scripts/modules/__init__.py`, give it an `enabled:`
  block in the profile, and describe its section in the composition file.
  The existing modules are short examples.
- **The look** of the email and page: the palette constants at the top of
  `scripts/brief_html.py`.

Run the tests with `python3 -m unittest discover -s tests`.

## Privacy and security

- **Keep your copy private.** It commits your briefs, calendar window, job
  list and plans every day. The workflows refuse to run in a public repo.
- Secrets (calendar link, passwords, tokens) live only in GitHub Actions
  secrets, never in files. Treat a calendar ICS link like a password: if it
  leaks, reset it (Google: *Reset* next to the secret address; iCloud: turn
  public sharing off and on), then update the secret.
- Anyone who can push to your repo can change what the routine does, since
  it follows `CLAUDE.md`. Don't give others write access.
- The routine reads web pages for the news. It has no email or other
  connectors, so a malicious page has little to work with; still, review
  what you enable.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No brief at all | Check the routine's latest run at claude.ai/code/routines. If it didn't run, the backup edition should arrive after `delivery.backup_after`. |
| The brief arrives an hour early or late | Routine schedules are in UTC and don't follow daylight saving time. Update the cron when the clocks change (`doctor.py` prints both). |
| No email or Telegram, but the brief is in `briefs/` | Look at **Actions → Deliver the brief**. A red run says which secret or setting is missing. Check `MORNING_BRIEF_ENABLED` is `true`. |
| Two emails, one of them garbled | Something other than `deliver.py` is emailing, usually a routine told to use an email connector. Only Actions should send email; remove the connector from the routine. |
| Workflows fail with 403 on push | Settings → Actions → General → Workflow permissions → Read and write. |
| "the calendar snapshot is N days old" | The calendar-refresh workflow is failing: open its latest run. Usually the ICS link was reset or the secret is wrong. |
| Event times are off by hours | Check `user.timezone`. Feeds that use Windows zone names fall back to your timezone. |
| The backup edition arrives hours late | GitHub delays scheduled runs at busy times. The backup is best-effort; the normal path (push) isn't affected. |
| A new artifact page every day | `state/history.json` `artifact.url` was lost. Set it back to the page's URL. |
| `doctor.py` reports a line number | The profile has a YAML mistake there: often a missing quote around a value with `: ` in it. |

## Credits

Built with Claude Code. MIT licensed: see [LICENSE](LICENSE).
