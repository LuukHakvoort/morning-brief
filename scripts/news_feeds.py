"""Headline-only news from free RSS/Atom feeds, for the backup edition.

Feeds come from profile.yaml `news.backup_feeds.headlines` / `.reports`
("Label | URL"). Items must carry a date within `news.max_age_days`, and no
link used in the last `news.dedupe_window_days` of briefs is repeated (the
same rules scripts/check_news.py applies to the routine's news section).
"""

import gzip
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import config
from check_news import normalise_url, recent_links

ATOM = "{http://www.w3.org/2005/Atom}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; morning-brief/1.0; +https://github.com/)",
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
    "Accept-Encoding": "gzip",
}


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def md_title(title):
    """Keep a headline safe inside a Markdown link."""
    return title.replace("[", "(").replace("]", ")").replace("*", "").replace("_", " ")


def md_url(url):
    return url.strip().replace("(", "%28").replace(")", "%29").replace(" ", "%20")


def parse_time(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(data):
    """All items of an RSS/Atom document (bytes), newest first."""
    if data[:2] == b"\x1f\x8b":  # gzip body even when the server doesn't say so
        data = gzip.decompress(data)
    root = ET.fromstring(data)
    out = []
    for node in list(root.iter("item")) + list(root.iter(ATOM + "entry")):
        title = clean(node.findtext("title") or node.findtext(ATOM + "title"))
        link = (node.findtext("link") or "").strip()
        if not link:
            el = node.find(ATOM + "link")
            link = el.get("href", "") if el is not None else ""
        when = parse_time(node.findtext("pubDate") or node.findtext(ATOM + "updated")
                          or node.findtext(ATOM + "published") or node.findtext("{http://purl.org/dc/elements/1.1/}date"))
        if title and link:
            out.append({"title": title, "link": link, "when": when})
    out.sort(key=lambda i: i["when"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out


def fetch_feed(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return parse_feed(resp.read(3_000_000))


def fresh_items(items, now, max_age_days, used):
    """Dated items inside the window, not already used, newest first."""
    keep, seen = [], set()
    for it in items:
        if it["when"] is None or now - it["when"] > timedelta(days=max_age_days):
            continue
        key = normalise_url(it["link"])
        if key in used or key in seen:
            continue
        seen.add(key)
        keep.append(it)
    return keep


def pick_round_robin(per_feed, count):
    """Take items across feeds in turn, so one busy feed can't fill the section.

    A story syndicated in two feeds is taken once."""
    picked, seen, i = [], set(), 0
    while len(picked) < count and any(i < len(items) for _, items in per_feed):
        for label, items in per_feed:
            if i < len(items) and len(picked) < count:
                link = items[i]["link"] if isinstance(items[i], dict) else items[i]
                key = normalise_url(link) if isinstance(link, str) else link
                if key not in seen:
                    seen.add(key)
                    picked.append((label, items[i]))
        i += 1
    return picked


def news_items(cfg, today, fetch=fetch_feed, now=None):
    """{'headlines': [(label, item)], 'reports': [...], 'failed': n, 'total': n}."""
    max_age = int(config.get(cfg, "news.max_age_days", 7))
    heading = str(config.get(cfg, "news.section_heading", "World pulse"))
    used = recent_links(today, int(config.get(cfg, "news.dedupe_window_days", 7)), heading=heading)
    now = now or datetime.now(timezone.utc)
    result, failed, total = {}, 0, 0
    for kind, count_key in (("headlines", "headline_count"), ("reports", "report_count")):
        per_feed = []
        for line in config.as_list(config.get(cfg, f"news.backup_feeds.{kind}", [])):
            label, url = config.split_link(line)
            if not url:
                continue
            total += 1
            try:
                per_feed.append((label, fresh_items(fetch(url), now, max_age, used)))
            except Exception as e:  # noqa: BLE001 -- one dead feed must not sink the brief
                config.log(f"feed failed: {label}: {type(e).__name__}: {e}")
                failed += 1
        result[kind] = pick_round_robin(per_feed, int(config.get(cfg, f"news.{count_key}", 5 if kind == "headlines" else 3)))
        used |= {normalise_url(it["link"]) for _, it in result[kind]}
    result["failed"], result["total"] = failed, total
    return result


def bullets(news):
    """Markdown bullets for the news section (every line must be a list item)."""
    out = []
    for kind, word in (("headlines", "Headline"), ("reports", "Report")):
        for label, it in news.get(kind, []):
            out.append(f"- **{word} · {config.short_date(it['when'].date())} · {label}**: "
                       f"[{md_title(it['title'])}]({md_url(it['link'])})")
    if not out:
        out.append("- Heads up: no fresh headlines could be fetched this morning, so skip the news today.")
    elif news.get("failed"):
        out.append(f"- Heads up: {news['failed']} of {news['total']} news feeds couldn't be reached this morning.")
    return out
