# Morning Brief — Composition Instructions

`config/profile.yaml` holds the facts about the reader. This file is **how**
Claude turns today's facts into the brief: voice, sections, order and the
rules each section follows. To change the tone or the structure, edit this
file (and `tone:` in profile.yaml), never the scripts.

> **Customize:** the blocks marked like this one are where most people make
> the brief their own. Everything else works as-is.

## Voice

Coach, not calendar app. Confident, warm, a little relentless. Short
sentences. Numbers as fuel, not pressure. Follow `tone.style` and
`tone.voice_notes`, avoid `tone.banned_phrases`, and use
`tone.example_opening` as the model for the first line.

> **Customize:** describe the reader in a sentence or two if it helps the
> voice ("a night owl who hates mornings: keep it light before 9").

## Where the facts come from

Run `python3 scripts/facts.py` (CLAUDE.md step 2) and use its JSON as the
facts. Don't recompute dates, rotations, picks or plans by hand: the
scripts already did, and `facts.py --save` records exactly what they chose.

- Always there: `today`, `weekday`, `title_line`, `is_weekly_extras_day`,
  `user`, `location` / `away`, `calendar.events_today`, `fixed_items_today`,
  `skipped_while_away`, `day_plan`, `rotations`, `week` (today + 6 days),
  `warnings`.
- Only when that module is enabled in profile.yaml: `countdowns`, `trips`,
  `workout`, `jobs`. **No key, no section**: never invent a section for a
  module that isn't in the facts.

Each entry in `warnings` becomes one short "heads up" line in the section it
belongs to. Never paste raw JSON, keys or file paths into the brief.

## Structure, every day

Start with `title_line` exactly as given, then these sections in this order.
Skip a section entirely when it has nothing to say.

1. **Opening line** (no heading): energetic, names today's single biggest
   lever. Let the facts decide what that is: a countdown at 0 days or a
   reminder due today, a trip day, today's first job application, the
   day-plan focus, or the nearest countdown.

2. **`## Countdown`** (if `countdowns.next` exists): the line
   `Countdown check: **N days** to <label> (<Wkd Mon D>).` on its own
   paragraph (the renderer turns it into the big number), then each of
   `countdowns.reminders_today` as a bullet, then one line naming the next
   one or two after it.

3. **`## Trip`** (if `trips.trip_today` or `trips.tasks_today`): day X of Y
   in the city, the sessions with time, title and place, arrival/departure
   notes on travel days, then each prep or follow-up task.

4. **`## Jobs`** (if `jobs` exists):
   - **Today's N applications**, numbered: role, organisation, location,
     the deadline in words ("closes Dec 3, in 4 days"), `pay_note` if
     present, one line on the angle to take (from `notes` and
     `jobs.profile_summary`), and the link.
   - Roles in `closing_7d` as one "also closing this week" line.
   - `follow_ups` as a short nudge to follow up.
   - If `todays_picks` is empty, say so and suggest where to look (the
     search settings under `jobs.search`).

   > **Customize:** add rules for how to tailor applications, e.g. "always
   > suggest one person to message at the organisation".

5. **`## Today's shape`**
   - `day_plan.today_output` as "**Today's focus:** …", with
     `tomorrow_output` as a one-line preview; `schedule_changes_today` as a
     list and `schedule_changes_upcoming` as "Coming up".
   - `fixed_items_today`; on away days, one line listing
     `skipped_while_away`.
   - **Calendar**: `calendar.events_today` in time order, all-day events
     first. Skip an event whose title matches a fixed item you already
     listed. If `calendar.enabled` but not `available`, say the calendar
     couldn't be read today rather than implying a free day.
   - Each of `rotations`: "**<name> (<minutes> min):** <text>", with the
     `url` as a link when there is one.
   - `workout.today` (every day: a run never replaces it), then the run:
     on a run day (`workout.runs.today_run`) the type, description, reason
     and the warm-up / cool-down links; otherwise one line for
     `workout.runs.next_run` if there is one.

   > **Customize:** add your own daily items here, e.g. "a 10-minute
   > journaling prompt that fits the day".

6. **`## World pulse`** (the heading is `news.section_heading`): a week of
   news from live web search across `news.topics`, curated hard: specific
   developments, not generic headlines.
   - **Headlines** (`news.headline_count`, 4-5 bullets): the biggest stories
     of the last `news.max_age_days` days. Format:
     `- **Headline · Nov 12 · Reuters**: what happened and why it matters to the reader ([link](url))`
   - **Reports and analysis** (`news.report_count`, 2-3 bullets): notable
     reports, studies or long reads. Format:
     `- **Report · Nov 11 · OECD**: the report and its key finding ([link](url))`
   - Every bullet has its date written like "Nov 12", a publisher and a
     source link, and doesn't repeat a link from the previous week of
     briefs. Undated items are not allowed. Every line in this section is
     a bullet (use `- Heads up: …` for a notice).

   > **Customize:** say what "why it matters" should connect to, e.g. "my
   > job applications in climate policy" or "my investing".

7. **`## Closing kick`**: one momentum line ending with a concrete
   "**First move for the next 30 minutes:** …".

> **Customize:** add your own sections between 4 and 5, e.g. "`## Fixtures`:
> web-search my football team's next match; if it's within 2 days, give the
> kick-off in my timezone". Sections that need live information use web
> search; sections that only reshape the facts don't.

## Weekly extras (on `delivery.weekly_extras_day`)

When `is_weekly_extras_day` is true, also:

- **`## Week ahead`** (after Jobs): one line per day from `week`: location
  if away, sessions, countdowns, fixed items, the main events and planned
  runs. Keep each line short.
- **Jobs refill**: if `jobs.needs_refill`, web-search for open roles
  matching `jobs.search` and `jobs.profile_summary`, and add the good ones
  to `state/job_pipeline.json` `items` (fields as in data/jobs.csv: `org`,
  `role`, `location`, `deadline`, `url`, `priority`, `pay`, `notes`). Only
  roles with a verified, still-open posting. Then re-run `facts.py` so
  today's picks include them. (On other days, refill only if
  `todays_picks` came back empty.)

> **Customize:** weekly research of your own, e.g. "3 events in my city this
> week" or "one new restaurant to try". Keep a list of what you've already
> suggested in state/history.json under a key of your choice to avoid
> repeats.

## Formats the scripts depend on (don't change these)

- The first line is `title_line`: `# <delivery.title> — <Weekday>, <Month D, YYYY>`.
  The email subject and the backup detection read it.
- `Countdown check: **N days** to …` starts its own line.
- The news section is `## <news.section_heading>` and every line in it is a
  bullet; `scripts/check_news.py` checks it.
- A brief containing the line `Backup edition:` is the automatic backup.
- Save the brief as `briefs/<today>.md`, where `<today>` is `facts.today`.

## Delivery

1. **Push notification** (`PushNotification`, status `"proactive"`): under
   200 characters, one line, plain text only. No Markdown and no tags of
   any kind (a tag-wrapped message arrives on the phone with no text).
   The single most energizing fact of the day.
2. **Persistent page** (if `artifact.enabled`): see CLAUDE.md step 6.
3. **The file** (`SendUserFile`, status `"proactive"`): the brief file with
   a one-line caption.
4. **Email and Telegram are not your job.** GitHub Actions sends them the
   moment your push lands (CLAUDE.md step 9). Never send the brief by email
   yourself, with any tool.

Never hand-write HTML: `scripts/brief_html.py` renders both the page and
the email from the Markdown.

## After sending

Run `python3 scripts/facts.py --save` once. It records today's rotation
positions, the week's run plan, today's job picks (use
`--save --serve-jobs KEY KEY …` with the `key`s you actually showed, if you
swapped one) and `last_brief_date`. Don't edit those parts of
`state/history.json` by hand, and never touch the `*_last_sent_date` keys
(GitHub Actions owns them).

## If something fails

Don't fail silently and don't dump errors into the brief. Write the brief
with whatever worked, and add one short coach-toned "heads up, X wasn't
available today" line where the missing piece would have been. If a script
errors, skip what it feeds and say so in one line.

A failed artifact publish or a failed push is different: a channel didn't
land. Say so plainly in your final message (CLAUDE.md step 10) and carry on
with the remaining steps.
