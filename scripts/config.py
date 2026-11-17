#!/usr/bin/env python3
"""Config loader and small shared helpers for the morning brief (stdlib only).

config/profile.yaml is read with a strict loader for a YAML *subset*:
  - maps and nested maps (indent with spaces, any consistent width)
  - lists of scalars and lists of maps ("- key: value")
  - "double" and 'single' quoted strings, [inline, lists], {} (empty map only)
  - block scalars:  key: >   (folded)   and   key: |   (literal)
  - comments (# ...) on their own line or after a value
  - true/false, null/~, integers and decimals; everything else is a string
Anything outside that subset (anchors, tags, multi-line plain values, tabs,
duplicate keys, "a: b: c") raises ConfigError with the line number, so a typo
fails loudly instead of being silently misread. Unlike YAML 1.1, unquoted
07:30 and 2026-11-16 stay strings, and yes/no are not booleans.

Paths: everything is relative to the repo root, or to $MORNING_BRIEF_ROOT if
set (the tests use that to work in a temporary copy).

CLI (handy in workflows and shell):
    python3 scripts/config.py today          today's date in user.timezone
    python3 scripts/config.py get news.max_age_days
"""

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
PROFILE = "config/profile.yaml"


class ConfigError(ValueError):
    def __init__(self, line, message):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


# ---------------------------------------------------------------- YAML subset

_INT = re.compile(r"^[-+]?\d+$")
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+)$")


def _strip_comment(s):
    """Drop a trailing '# comment' that isn't inside quotes."""
    q = None
    i = 0
    while i < len(s):
        c = s[i]
        if q:
            if q == '"' and c == "\\":
                i += 2
                continue
            if c == q:
                if q == "'" and s[i + 1:i + 2] == "'":
                    i += 2
                    continue
                q = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t[,{:-"):
            q = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _find_colon(s):
    """Index of the key/value colon (': ' or a trailing ':') outside quotes, or -1."""
    q = None
    for i, c in enumerate(s):
        if q:
            if c == q:
                q = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t[,{"):
            q = c
        elif c == ":" and (i + 1 == len(s) or s[i + 1] in " \t"):
            return i
    return -1


def _quoted(s, line):
    """(value, rest) for a string starting with a quote."""
    q = s[0]
    out, i = [], 1
    while i < len(s):
        c = s[i]
        if q == '"' and c == "\\" and i + 1 < len(s):
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(s[i + 1], "\\" + s[i + 1]))
            i += 2
            continue
        if c == q:
            if q == "'" and s[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), s[i + 1:]
        out.append(c)
        i += 1
    raise ConfigError(line, f"unclosed {q}quote{q}")


def _split_inline(body, line):
    items, cur, q = [], [], None
    for c in body:
        if q:
            cur.append(c)
            if c == q:
                q = None
        elif c in "\"'":
            q = c
            cur.append(c)
        elif c == ",":
            items.append("".join(cur).strip())
            cur = []
        elif c in "[]{}":
            raise ConfigError(line, "nested [ ] or { } inside an inline list isn't supported")
        else:
            cur.append(c)
    if q:
        raise ConfigError(line, "unclosed quote in inline list")
    last = "".join(cur).strip()
    if last:
        items.append(last)
    elif items:
        raise ConfigError(line, "trailing comma in inline list")
    return items


def _scalar(s, line):
    s = s.strip()
    if not s:
        return None
    if s[0] in "\"'":
        value, rest = _quoted(s, line)
        if rest.strip():
            raise ConfigError(line, f"unexpected text after the closing quote: {rest.strip()!r}")
        return value
    if s[0] == "[":
        if not s.endswith("]"):
            raise ConfigError(line, "inline list must end with ]")
        return [_scalar(x, line) for x in _split_inline(s[1:-1], line)]
    if s[0] == "{":
        if s.replace(" ", "") == "{}":
            return {}
        raise ConfigError(line, "inline maps aren't supported; use an indented block")
    if s[0] in "&*!%@`|>":
        raise ConfigError(line, f"values starting with {s[0]!r} must be quoted")
    if _find_colon(s) != -1:
        raise ConfigError(line, "a value can't contain ': ' unless it is quoted")
    if s in ("null", "Null", "NULL", "~"):
        return None
    if s in ("true", "True", "TRUE"):
        return True
    if s in ("false", "False", "FALSE"):
        return False
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


class _Parser:
    def __init__(self, text):
        self.raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.lines = []  # [line_no, indent, content]
        for no, rawline in enumerate(self.raw, 1):
            stripped = rawline.lstrip(" ")
            if stripped.startswith("\t"):
                raise ConfigError(no, "tab used for indentation; use spaces")
            content = _strip_comment(stripped)
            if not content or (content == "---" and not self.lines):
                continue
            self.lines.append([no, len(rawline) - len(stripped), content])
        self.i = 0

    def peek(self):
        return self.lines[self.i] if self.i < len(self.lines) else None

    @staticmethod
    def is_item(content):
        return content == "-" or content.startswith("- ")

    def node(self, indent):
        no, ind, content = self.peek()
        return self.seq(ind) if self.is_item(content) else self.mapping(ind)

    def mapping(self, indent):
        out = {}
        while self.peek():
            no, ind, content = self.peek()
            if ind < indent:
                break
            if ind > indent:
                raise ConfigError(no, "unexpected indentation (a multi-line value must be quoted or use > / |)")
            if self.is_item(content):
                raise ConfigError(no, "a list item where a 'key: value' line was expected")
            colon = _find_colon(content)
            if colon <= 0:
                raise ConfigError(no, f"expected 'key: value', got {content!r}")
            key = content[:colon].strip()
            if key[0] in "\"'":
                key, rest = _quoted(key, no)
                if rest.strip():
                    raise ConfigError(no, "bad quoted key")
            if key in out:
                raise ConfigError(no, f"duplicate key {key!r}")
            self.i += 1
            out[key] = self.value(content[colon + 1:].strip(), indent, no)
        return out

    def value(self, rest, indent, no):
        if rest and rest[0] in "|>" and re.fullmatch(r"[|>][-+]?", rest):
            return self.block_scalar(rest, indent, no)
        if rest:
            return _scalar(rest, no)
        nxt = self.peek()
        if nxt and nxt[1] > indent:
            return self.node(nxt[1])
        if nxt and nxt[1] == indent and self.is_item(nxt[2]):
            return self.seq(indent)
        return None

    def seq(self, indent):
        out = []
        while self.peek():
            no, ind, content = self.peek()
            if ind < indent or (ind == indent and not self.is_item(content)):
                break
            if ind > indent:
                raise ConfigError(no, "unexpected indentation inside a list")
            body = content[1:].lstrip(" ")
            if not body:
                self.i += 1
                nxt = self.peek()
                out.append(self.node(nxt[1]) if nxt and nxt[1] > indent else None)
            elif body[0] not in "\"'[{" and _find_colon(body) > 0:
                # "- key: value" starts a map whose keys sit at the item's text column
                self.lines[self.i] = [no, ind + len(content) - len(body), body]
                out.append(self.mapping(self.lines[self.i][1]))
            else:
                self.i += 1
                out.append(_scalar(body, no))
        return out

    def block_scalar(self, indicator, indent, no):
        collected, last_no = [], no
        for k in range(no, len(self.raw)):  # self.raw[no] is the line after the key
            line = self.raw[k]
            if line.strip() and len(line) - len(line.lstrip(" ")) <= indent:
                break
            collected.append(line)
            last_no = k + 1
        while collected and not collected[-1].strip():
            collected.pop()
        while self.peek() and self.peek()[0] <= last_no:
            self.i += 1
        if not collected:
            return ""
        width = min(len(l) - len(l.lstrip(" ")) for l in collected if l.strip())
        body = [l[width:] if l.strip() else "" for l in collected]
        if indicator[0] == "|":
            text = "\n".join(body)
        else:
            paras, cur = [], []
            for l in body:
                if l:
                    cur.append(l.strip())
                else:
                    paras.append(" ".join(cur))
                    cur = []
            paras.append(" ".join(cur))
            text = "\n".join(paras)
        return text if indicator.endswith("-") else text + "\n"


def parse_yaml(text):
    p = _Parser(text)
    if not p.peek():
        return {}
    result = p.node(p.peek()[1])
    if p.peek():
        raise ConfigError(p.peek()[0], "unexpected content (check the indentation)")
    return result


# ---------------------------------------------------------------- paths + profile

def root():
    return os.environ.get("MORNING_BRIEF_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def path(rel):
    return rel if os.path.isabs(rel) else os.path.join(root(), rel)


def read_text(rel):
    with open(path(rel), "r", encoding="utf-8") as f:
        return f.read()


def load_profile():
    """The parsed profile. Raises ConfigError (with a line number) or OSError."""
    data = parse_yaml(read_text(PROFILE))
    if not isinstance(data, dict):
        raise ConfigError(None, "profile.yaml must be a map of sections at the top level")
    return data


def get(cfg, dotted, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def enabled(cfg, name):
    return get(cfg, f"{name}.enabled", False) is True


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def tz(cfg):
    name = get(cfg, "user.timezone", "UTC")
    try:
        return ZoneInfo(str(name))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def now_local(cfg):
    return datetime.now(tz(cfg))


def today_local(cfg):
    return now_local(cfg).date()


def weekly_extras_day(cfg):
    return str(get(cfg, "delivery.weekly_extras_day", "Monday")).strip().capitalize()


def brief_title(cfg):
    return str(get(cfg, "delivery.title", "Morning Brief")).strip() or "Morning Brief"


# ---------------------------------------------------------------- json + state

def read_json(rel, default=None):
    try:
        with open(path(rel), "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(rel, data):
    p = path(rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)


def load_history():
    data = read_json("state/history.json", {})
    return data if isinstance(data, dict) else {}


def save_history(hist):
    write_json("state/history.json", hist)


# ---------------------------------------------------------------- text + dates

def log(msg):
    print(msg, file=sys.stderr, flush=True)


def to_date(value):
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return None


def pretty_date(d):
    """'Monday, November 16, 2026'"""
    return f"{WEEKDAYS[d.weekday()]}, {MONTHS[d.month - 1]} {d.day}, {d.year}"


def short_date(d):
    """'Nov 16'"""
    return f"{MONTHS[d.month - 1][:3]} {d.day}"


def shorten(text, limit):
    """Collapse whitespace and cut at a word boundary with an ellipsis."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:—- ") + "…"


def split_link(text):
    """'Some title | https://…' -> ('Some title', 'https://…'); no link -> (text, None)."""
    text = str(text or "").strip()
    m = re.match(r"^(.*?)\s*\|\s*(https?://\S+)\s*$", text)
    return (m.group(1).strip(), m.group(2)) if m else (text, None)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "item"


def main(argv):
    if len(argv) >= 1 and argv[0] == "today":
        try:
            print(today_local(load_profile()).isoformat())
        except (ConfigError, OSError):
            print(datetime.now(timezone.utc).date().isoformat())
        return 0
    if len(argv) == 2 and argv[0] == "get":
        value = get(load_profile(), argv[1])
        print(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        return 0
    print(__doc__.strip().split("CLI")[1] if "CLI" in __doc__ else __doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
