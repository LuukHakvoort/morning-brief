#!/usr/bin/env python3
"""Render a brief's Markdown into styled HTML (email + artifact page) or plain text.

Usage:
    python3 scripts/brief_html.py <brief_file.md> [--format html|artifact|plain]

One parser feeds all three renderers, so the email, the persistent page and
the plain-text alternative never drift apart in structure. They differ only
in typography: email clients can't load web fonts, so the email uses safe
fallbacks while the artifact page loads real display/body faces.

Design: a quiet "policy brief" look. A deep blue carries structure
(masthead, section tags, rules, links); a warm amber is reserved for the
one momentum stat, the "Countdown check:" days-to-go number. Sections get
small filled tags instead of emoji, separated by hairline rules. Change
the palette constants below to restyle everything.

Contract with config/brief_composition.md (don't rename these):
  - the first line is "# <title> — <Weekday>, <Month D, YYYY>"
  - "Countdown check: **N days** to ..." starts its own line
  - sections are "## Heading"; known headings map to short tags via
    SECTION_TAGS, anything else is shown as its own (upper-cased) text
  - paragraphs may mix a lead-in line with "- " bullets or "1. " items

Stdlib only, no network.
"""

import argparse
import html
import re
import sys

TITLE_RE = re.compile(r"^# (.+)$", re.MULTILINE)
HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
SOURCES_RE = re.compile(r"^Sources:\s*$", re.MULTILINE)
COUNTDOWN_RE = re.compile(r"^Countdown check:\s*(.*)$", re.MULTILINE)
COUNTDOWN_NUM_RE = re.compile(r"\*\*(\d+)\s+days?\*\*")

SECTION_TAGS = {
    "countdown": "COUNTDOWN",
    "trip": "TRIP",
    "jobs": "CAREER",
    "career": "CAREER",
    "week ahead": "WEEK",
    "today's shape": "TODAY",
    "world pulse": "WORLD",
    "closing kick": "MOMENTUM",
}
LIST_ITEM_RE = re.compile(r"^(?:- |(\d+)\. )(.*)$")

# ---- "Policy Brief" palette: institutional blue (structure) + amber
# (personal momentum, used only for the countdown stat) ----
INK = "#1C1C1A"
PAPER = "#F1F1EC"
CARD = "#FFFFFF"
BLUE = "#1E3A5F"
BLUE_TINT = "#E7ECF1"
AMBER = "#B45309"
MUTED = "#6B7280"
HAIRLINE = "#DBDBD2"

# Email must use web-safe fallback stacks -- Google Fonts don't render in
# most mail clients. The Artifact page loads real faces (see ARTIFACT_HEAD).
EMAIL_SERIF = "Georgia, 'Times New Roman', serif"
EMAIL_SANS = "Helvetica, Arial, sans-serif"
ARTIFACT_SERIF = "'Fraunces', Georgia, serif"
ARTIFACT_SANS = "'IBM Plex Sans', Helvetica, Arial, sans-serif"


# ---------- parsing ----------

def parse_brief(text):
    title_m = TITLE_RE.search(text)
    title = title_m.group(1).strip() if title_m else "Morning Brief"
    after_title = text[title_m.end():] if title_m else text

    heading_matches = list(HEADING_RE.finditer(after_title))
    if heading_matches:
        lede = after_title[: heading_matches[0].start()].strip()
    else:
        lede = after_title.strip()

    sections = []
    for i, m in enumerate(heading_matches):
        heading = m.group(1).strip()
        start = m.end()
        end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(after_title)
        body = after_title[start:end].strip()
        sections.append({"heading": heading, "body": body})

    return title, lede, sections


def extract_sources(body):
    m = SOURCES_RE.search(body)
    if not m:
        return body, None
    main = body[: m.start()].rstrip()
    sources = body[m.end():].strip()
    return main, sources


def extract_countdown(body):
    m = COUNTDOWN_RE.search(body)
    if not m:
        return body, None, None
    sentence = m.group(0).strip()
    rest = (body[: m.start()] + body[m.end():]).strip()
    rest = re.sub(r"\n{3,}", "\n\n", rest)
    num_m = COUNTDOWN_NUM_RE.search(sentence)
    number = num_m.group(1) if num_m else None
    return rest, sentence, number


def inline_html(text, accent=BLUE):
    text = html.escape(text, quote=False)  # a bare "&" or "<" in a headline must not break the markup
    text = LINK_RE.sub(
        lambda m: f'<a href="{m.group(2).replace(chr(34), "%22")}" '
                  f'style="color:{accent};text-decoration:underline;">{m.group(1)}</a>',
        text,
    )
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = ITALIC_RE.sub(r"<em>\1</em>", text)
    return text


def inline_plain(text):
    text = LINK_RE.sub(lambda m: f"{m.group(1)} — {m.group(2)}", text)
    text = BOLD_RE.sub(r"\1", text)
    text = ITALIC_RE.sub(r"\1", text)
    return text


# ---------- shared HTML rendering (parameterized by font stack) ----------

def blocks(body):
    """Split Markdown-ish text into ("text", str) and ("item", marker, str) blocks.

    A paragraph may mix a lead-in line with "- " bullets or "1. " numbered
    items; consecutive plain lines are joined into one text block."""
    out = []
    for para in body.split("\n\n"):
        lines = [l.strip() for l in para.strip().split("\n") if l.strip()]
        text = []
        for l in lines:
            m = LIST_ITEM_RE.match(l)
            if m:
                if text:
                    out.append(("text", " ".join(text)))
                    text = []
                out.append(("item", f"{m.group(1)}." if m.group(1) else "—", m.group(2).strip()))
            else:
                text.append(l)
        if text:
            out.append(("text", " ".join(text)))
    return out


def paragraphs_html(body, sans):
    out = []
    for b in blocks(body):
        if b[0] == "item":
            out.append(
                f'<div style="margin:0 0 8px 0;padding-left:22px;position:relative;'
                f'color:{INK};font-family:{sans};font-size:15px;line-height:1.6;">'
                f'<span style="position:absolute;left:0;color:{BLUE};">{b[1]}</span>'
                f'{inline_html(b[2])}</div>'
            )
        else:
            out.append(
                f'<p style="margin:0 0 12px 0;color:{INK};font-family:{sans};'
                f'font-size:15px;line-height:1.6;">{inline_html(b[1])}</p>'
            )
    return "".join(out)


def section_html(section, serif, sans, is_first):
    heading, body = section["heading"], section["body"]
    tag = SECTION_TAGS.get(heading.lower(), heading.upper())

    body, sources = extract_sources(body)
    body, countdown_sentence, countdown_num = extract_countdown(body)

    top_rule = "" if is_first else f'<div style="border-top:1px solid {HAIRLINE};margin-bottom:24px;"></div>'

    parts = [
        f'<tr><td style="padding:{"0" if is_first else "24px"} 32px 0 32px;">',
        top_rule,
        f'<span style="display:inline-block;background-color:{BLUE};color:#FFFFFF;'
        f'font-family:{sans};font-size:11px;font-weight:600;letter-spacing:1.2px;'
        f'padding:4px 10px;margin-bottom:14px;">{tag}</span>',
        "</td></tr>",
    ]

    if countdown_sentence:
        rest_of_sentence = countdown_sentence
        stat_html = ""
        if countdown_num:
            rest_of_sentence = COUNTDOWN_NUM_RE.sub("", countdown_sentence, count=1)
            rest_of_sentence = re.sub(r"^Countdown check:\s*", "", rest_of_sentence).strip(" .—-")
            # Stacked (not flex/inline-block side-by-side) so this renders
            # identically in Outlook's Word-based engine, not just browsers.
            stat_html = (
                f'<div style="margin:4px 0 10px 0;">'
                f'<div style="font-family:{serif};font-size:44px;font-weight:600;color:{AMBER};'
                f'line-height:1;">{countdown_num}</div>'
                f'<div style="font-family:{sans};font-size:12px;font-weight:600;letter-spacing:0.8px;'
                f'color:{AMBER};text-transform:uppercase;margin-top:2px;">days to go</div></div>'
            )
        parts.append(
            f'<tr><td style="padding:0 32px 12px 32px;">'
            f'{stat_html}'
            f'<p style="margin:0 0 12px 0;color:{MUTED};font-family:{sans};font-size:13px;'
            f'font-style:italic;line-height:1.5;">{inline_html(rest_of_sentence, accent=AMBER) if countdown_num else inline_html(countdown_sentence, accent=AMBER)}</p>'
            f"</td></tr>"
        )

    parts.append(f'<tr><td style="padding:0 32px 4px 32px;">{paragraphs_html(body, sans)}</td></tr>')

    if sources:
        source_lines = "".join(
            f'<div style="margin:0 0 4px 0;">{inline_html(l.lstrip("- ").strip())}</div>'
            for l in sources.split("\n")
            if l.strip()
        )
        parts.append(
            f'<tr><td style="padding:8px 32px 4px 32px;">'
            f'<div style="font-family:{sans};font-size:12px;font-style:italic;color:{MUTED};'
            f'line-height:1.5;">{source_lines}</div>'
            f"</td></tr>"
        )

    return "".join(parts)


def render_body_content(title, lede, sections, date_label, serif, sans):
    title, date_label = html.escape(title, quote=False), html.escape(date_label, quote=False)
    lede_html = paragraphs_html(lede, sans) if lede else ""
    sections_html = "".join(section_html(s, serif, sans, i == 0) for i, s in enumerate(sections))

    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:{PAPER};">
<tr><td align="center" style="padding:32px 12px;">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" style="max-width:640px;width:100%;background-color:{CARD};">
<tr><td style="background-color:{BLUE};padding:10px 32px;">
<div style="font-family:{sans};font-size:11px;font-weight:600;letter-spacing:2px;color:#FFFFFF;text-transform:uppercase;">{date_label}</div>
</td></tr>
<tr><td style="padding:28px 32px 8px 32px;">
<div style="font-family:{serif};font-size:28px;font-weight:600;color:{INK};line-height:1.25;">{title}</div>
</td></tr>
<tr><td style="padding:0 32px 20px 32px;">{lede_html}</td></tr>
{sections_html}
<tr><td style="padding:20px 32px 28px 32px;border-top:1px solid {HAIRLINE};margin-top:8px;">
<div style="font-family:{sans};font-size:11px;color:{MUTED};padding-top:16px;">
Your morning brief — generated fresh every day.
</div>
</td></tr>
</table>
</td></tr>
</table>"""


def render_html(title, lede, sections):
    """Full standalone document for the Gmail body -- safe web fonts only."""
    date_label = title.split("—", 1)[-1].strip() if "—" in title else title
    body_content = render_body_content(title, lede, sections, date_label, EMAIL_SERIF, EMAIL_SANS)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{html.escape(title, quote=False)}</title>
</head>
<body style="margin:0;padding:0;background-color:{PAPER};">
{body_content}
</body>
</html>
"""


def render_artifact(title, lede, sections):
    """Content-only fragment for the Artifact tool, which applies its own
    <!doctype>/<html>/<head>/<body> skeleton -- no DOCTYPE/html/head/body
    tags here, just <title> + <style> + content, per Artifact conventions.
    Loads real display/body faces via Google Fonts (the one host the
    Artifact CSP admits) and supports light/dark via CSS custom properties."""
    date_label = title.split("—", 1)[-1].strip() if "—" in title else title
    body_content = render_body_content(
        title, lede, sections, date_label, "var(--font-serif)", "var(--font-sans)"
    )
    return f"""<title>{html.escape(title, quote=False)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink: {INK}; --paper: {PAPER}; --card: {CARD}; --blue: {BLUE};
    --blue-tint: {BLUE_TINT}; --amber: {AMBER}; --muted: {MUTED}; --hairline: {HAIRLINE};
    --font-serif: {ARTIFACT_SERIF}; --font-sans: {ARTIFACT_SANS};
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ink: #EDECE7; --paper: #17181B; --card: #202226; --blue: #7DA0C4;
      --blue-tint: #26313D; --amber: #F0A857; --muted: #9AA1AC; --hairline: #33353A;
    }}
  }}
  :root[data-theme="dark"] {{
    --ink: #EDECE7; --paper: #17181B; --card: #202226; --blue: #7DA0C4;
    --blue-tint: #26313D; --amber: #F0A857; --muted: #9AA1AC; --hairline: #33353A;
  }}
  body {{ background: var(--paper); margin: 0; }}
</style>
<div style="background-color:var(--paper);">
{body_content}
</div>"""


# ---------- plain-text rendering (fallback if Gmail HTML doesn't render) ----------

def paragraphs_plain(body):
    out = []
    for b in blocks(body):
        if b[0] == "item":
            out.append(f"{b[1]} {inline_plain(b[2])}")
        else:
            out.append(("\n" if out else "") + inline_plain(b[1]))
    return "\n".join(out).strip()


def render_plain(title, lede, sections):
    rule = "─" * 40
    out = [title.upper(), rule, ""]
    if lede:
        out.append(paragraphs_plain(lede))
        out.append("")
    for s in sections:
        heading, body = s["heading"], s["body"]
        tag = SECTION_TAGS.get(heading.lower(), heading.upper())
        body, sources = extract_sources(body)
        body, countdown_sentence, _ = extract_countdown(body)
        out.append(f"[{tag}]")
        out.append(rule)
        if countdown_sentence:
            out.append(inline_plain(countdown_sentence))
            out.append("")
        out.append(paragraphs_plain(body))
        if sources:
            out.append("")
            out.append("Sources:")
            out.append(inline_plain(sources))
        out.append("")
    return "\n".join(out).strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("brief_file")
    ap.add_argument("--format", choices=["html", "artifact", "plain"], default="html")
    args = ap.parse_args()

    with open(args.brief_file, "r", encoding="utf-8") as f:
        text = f.read()

    title, lede, sections = parse_brief(text)

    if args.format == "html":
        sys.stdout.write(render_html(title, lede, sections))
    elif args.format == "artifact":
        sys.stdout.write(render_artifact(title, lede, sections))
    else:
        sys.stdout.write(render_plain(title, lede, sections))


if __name__ == "__main__":
    main()
