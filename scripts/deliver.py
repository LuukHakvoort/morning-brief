#!/usr/bin/env python3
"""Deliver today's brief by Telegram and email (run by GitHub Actions, not by Claude).

The single entry point of .github/workflows/deliver.yml. Plain HTTPS/SMTP,
so it works whether or not any Claude session or usage allowance is
available. One run does everything:

  1. Gate: scheduled fires only act between delivery.backup_after and
     delivery.backup_until (local time); any run stops early if every
     enabled channel already went out today. Idempotent, so retries and
     extra fires are harmless.
  2. If the Claude routine already pushed briefs/<today>.md, use it. Otherwise
     (scheduled or manual runs only) build the free backup edition with
     scripts/fallback_brief.py.
  3. Send each enabled channel that hasn't gone out today: Telegram (a short
     teaser, then the text) and email (styled HTML plus a plain-text part).
     This script is the ONLY sender: the routine never emails, because a
     model copying ~30 KB of HTML into a tool call is how you get garbled
     duplicates.
  4. Record telegram_last_sent_date / email_last_sent_date per channel in
     state/history.json, so a retry resends only what failed. On a failure,
     send one alert per day through whichever channel still works.

Usage (normally the workflow, which passes EVENT / FORCE in the environment):
    python3 scripts/deliver.py [--event schedule|push|workflow_dispatch] [--force] [--dry-run]

--force   ignore the gate and re-send today's brief on every enabled channel
          (never overwrites an existing brief).
--dry-run show what would be sent; send and write nothing (no backup build).

Secrets (environment): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, SMTP_PASSWORD,
optional SMTP_USERNAME (defaults to email.to). Exit code 1 if anything
failed, so the workflow run turns red and GitHub notifies you.
"""

import argparse
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from fallback_brief import build_and_write  # noqa: E402

TG_LIMIT = 3800  # Telegram caps a message at 4096 chars; leave room for the "Part i/n" prefix
SENT_KEY = {"telegram": "telegram_last_sent_date", "email": "email_last_sent_date"}
log = config.log


def with_retries(fn, what, tries=3):
    for i in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            log(f"{what}: attempt {i}/{tries} failed: {type(e).__name__}: {e}")
            if i == tries:
                raise
            time.sleep(2 * i * i)


# ---------- brief text ----------

def read_brief(path):
    """The brief's Markdown without any leading ---frontmatter---."""
    with open(path, "r", encoding="utf-8") as f:
        return re.sub(r"\A---\n.*?\n---\n", "", f.read(), flags=re.DOTALL)


def plain_text(chunk):
    chunk = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 — \2", chunk)
    chunk = re.sub(r"^#{1,6}\s+", "", chunk, flags=re.MULTILINE)
    chunk = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), chunk)
    chunk = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", chunk)
    return re.sub(r"\n{3,}", "\n\n", chunk).strip()


def telegram_chunks(brief_text, limit=TG_LIMIT):
    """Plain-text messages of at most `limit` chars, split on section boundaries."""
    pieces = []
    for section in re.split(r"\n(?=## )", brief_text):
        section = plain_text(section)
        if len(section) <= limit:
            pieces.append(section)
            continue
        for para in section.split("\n\n"):
            while len(para) > limit:
                pieces.append(para[:limit])
                para = para[limit:]
            pieces.append(para)
    chunks, cur = [], ""
    for piece in filter(None, pieces):
        joined = f"{cur}\n\n{piece}" if cur else piece
        if cur and len(joined) > limit:
            chunks.append(cur)
            cur = piece
        else:
            cur = joined
    return chunks + ([cur] if cur else [])


def teaser_from_brief(brief_text, date_pretty):
    """A push-style one-liner: the brief's opening line."""
    lines = [l.strip() for l in brief_text.splitlines()[1:] if l.strip() and not l.lstrip().startswith("#")]
    return config.shorten(plain_text(lines[0]), 180) if lines else f"Your morning brief for {date_pretty} is ready."


def title_date(brief_text, fallback):
    """'November 16, 2026' from '# <title> — Monday, November 16, 2026'."""
    m = re.search(r"^# .+? — (.+)$", brief_text, re.MULTILINE)
    return m.group(1).split(", ", 1)[-1].strip() if m else fallback


# ---------- Telegram ----------

def telegram_send(text):
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secrets are not set")

    def once():
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": True}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            if e.code == 429:  # honour Telegram's flood-control hint
                m = re.search(r'"retry_after":\s*(\d+)', detail)
                time.sleep(min(int(m.group(1)) if m else 5, 30))
            raise RuntimeError(f"Telegram HTTP {e.code}: {detail}") from None  # never echo the URL: it holds the token
        if not body.get("ok"):
            raise RuntimeError(f"Telegram said not ok: {str(body)[:300]}")

    with_retries(once, "telegram")


def deliver_telegram(brief_text, teaser):
    telegram_send(teaser)  # short message first: this is what pops up on the phone
    chunks = telegram_chunks(brief_text)
    for i, chunk in enumerate(chunks, start=1):
        telegram_send(f"Part {i}/{len(chunks)}\n\n{chunk}" if len(chunks) > 1 else chunk)
        time.sleep(1)


# ---------- email ----------

def render(brief_path, fmt):
    return subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "brief_html.py"),
                           brief_path, "--format", fmt], check=True, capture_output=True, text=True).stdout


def email_settings(cfg):
    to = str(config.get(cfg, "email.to", "")).strip()
    password = (os.environ.get("SMTP_PASSWORD") or "").replace(" ", "")
    if not to or not password:
        raise RuntimeError("email.to in profile.yaml / the SMTP_PASSWORD secret is not set")
    return {"to": to, "user": os.environ.get("SMTP_USERNAME") or to, "password": password,
            "host": str(config.get(cfg, "email.smtp_host", "smtp.gmail.com")),
            "port": int(config.get(cfg, "email.smtp_port", 465))}


def send_mail(msg, s):
    def once():
        if s["port"] == 465:
            with smtplib.SMTP_SSL(s["host"], 465, timeout=30, context=ssl.create_default_context()) as smtp:
                smtp.login(s["user"], s["password"])
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s["host"], s["port"], timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(s["user"], s["password"])
                smtp.send_message(msg)

    with_retries(once, "email")


def build_email(cfg, brief_path, date_pretty, sender):
    prefix = str(config.get(cfg, "email.subject_prefix", config.brief_title(cfg)))
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = f"{prefix} — {date_pretty}", sender, str(config.get(cfg, "email.to"))
    msg.set_content(render(brief_path, "plain"))
    msg.add_alternative(render(brief_path, "html"), subtype="html")
    return msg


def deliver_email(cfg, brief_path, date_pretty):
    s = email_settings(cfg)
    send_mail(build_email(cfg, brief_path, date_pretty, s["user"]), s)


# ---------- alerts + state ----------

def deliver_alert(cfg, text):
    """Failure notice through the first enabled channel that works."""
    if config.enabled(cfg, "telegram"):
        try:
            telegram_send(f"Morning brief problem: {text}")
            return
        except Exception as e:  # noqa: BLE001
            log(f"alert via telegram failed: {e}")
    if config.enabled(cfg, "email"):
        s = email_settings(cfg)
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = "Morning brief problem", s["user"], s["to"]
        msg.set_content(text)
        send_mail(msg, s)


def alert_once(cfg, iso_today, text, force=False):
    """At most one alert per day, so hourly retries of a broken setup don't spam."""
    hist = config.load_history()
    if hist.get("alert_last_sent_date") == iso_today and not force:
        log(f"an alert was already sent today ({iso_today}); not sending another")
        return
    try:
        deliver_alert(cfg, text)
    except Exception as e:  # noqa: BLE001
        log(f"could not send the alert through any channel: {e}")
        return
    hist["alert_last_sent_date"] = iso_today
    config.save_history(hist)


# ---------- the daily run ----------

def in_backup_window(cfg, now):
    start = config.get(cfg, "delivery.backup_after", "")
    if not start:  # default: an hour after the routine's time
        h, m = [int(x) for x in str(config.get(cfg, "delivery.time_local", "07:30")).split(":")[:2]]
        start = f"{min(h + 1, 23):02d}:{m:02d}"
    end = str(config.get(cfg, "delivery.backup_until", "18:00"))
    return str(start)[:5] <= now.strftime("%H:%M") < end[:5]


def run(cfg, now, event, force=False, dry_run=False):
    today, iso = now.date(), now.date().isoformat()
    channels = [c for c in ("telegram", "email") if config.enabled(cfg, c)]
    if not channels:
        log("no delivery channel is enabled (telegram.enabled / email.enabled in profile.yaml) - nothing to do")
        return 0
    if event == "schedule" and not force and not in_backup_window(cfg, now):
        log(f"local time is {now:%H:%M}, outside delivery.backup_after..backup_until - skipping this fire")
        return 0
    hist = config.load_history()
    pending = [c for c in channels if force or hist.get(SENT_KEY[c]) != iso]
    if not pending:
        log(f"{', '.join(SENT_KEY[c] for c in channels)} already {iso} - nothing left to do")
        return 0

    brief_path = config.path(f"briefs/{iso}.md")
    built_teaser = None
    if not os.path.exists(brief_path):
        if event == "push":  # a push means the routine's brief just landed; the backup is the schedule's job
            log(f"pushed, but there is no briefs/{iso}.md yet - nothing to send")
            return 0
        if dry_run:
            log(f"dry run: there is no briefs/{iso}.md, so a real run would build the backup edition now")
            return 0
        try:
            built_teaser = build_and_write(today)
        except Exception as e:  # noqa: BLE001
            log(f"backup brief failed: {type(e).__name__}: {e}")
            alert_once(cfg, iso, f"the backup brief for {iso} could not be built ({type(e).__name__}: {str(e)[:160]}).", force)
            return 1

    brief_text = read_brief(brief_path)
    date_pretty = title_date(brief_text, iso)
    teaser = built_teaser or teaser_from_brief(brief_text, date_pretty)
    if dry_run:
        log(f"dry run: would send {', '.join(pending)} for {iso}")
        log(f"  telegram teaser: {teaser}")
        log(f"  telegram messages after the teaser: {len(telegram_chunks(brief_text))}")
        log(f"  email subject: {config.get(cfg, 'email.subject_prefix', config.brief_title(cfg))} — {date_pretty}")
        return 0

    senders = {"telegram": lambda: deliver_telegram(brief_text, teaser),
               "email": lambda: deliver_email(cfg, brief_path, date_pretty)}
    failures, sent = [], []
    for name in pending:
        try:
            senders[name]()
            log(f"{name}: delivered")
            sent.append(name)
        except Exception as e:  # noqa: BLE001
            log(f"{name}: FAILED: {type(e).__name__}: {e}")
            failures.append(f"{name} ({type(e).__name__}: {str(e)[:160]})")
    if sent:  # per channel, even on a partial failure, so a retry resends only what failed
        hist = config.load_history()  # fresh: the backup build may have saved rotation state
        for name in sent:
            hist[SENT_KEY[name]] = iso
        config.save_history(hist)
    if failures:
        alert_once(cfg, iso, "delivery failed for " + "; ".join(failures) + ". The brief is in the repo under briefs/.", force)
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--event", default=os.environ.get("EVENT") or "manual",
                    help="GitHub event that started this run (schedule|push|workflow_dispatch)")
    ap.add_argument("--force", action="store_true", default=os.environ.get("FORCE", "").lower() == "true",
                    help="ignore the gate and re-send today's brief on every enabled channel")
    ap.add_argument("--dry-run", action="store_true", help="show what would be sent; send and write nothing")
    args = ap.parse_args()
    try:
        cfg = config.load_profile()
    except (config.ConfigError, OSError) as e:
        log(f"config/profile.yaml can't be read: {e}")
        return 1
    now = config.now_local(cfg)
    try:
        return run(cfg, now, args.event, args.force, args.dry_run)
    except Exception as e:  # noqa: BLE001
        log(f"delivery crashed: {type(e).__name__}: {e}")
        if not args.dry_run:
            alert_once(cfg, now.date().isoformat(), f"delivery crashed ({type(e).__name__}: {str(e)[:160]}).", args.force)
        return 1


if __name__ == "__main__":
    sys.exit(main())
