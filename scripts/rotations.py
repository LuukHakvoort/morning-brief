"""Daily rotations: one item per day from a list, cycling, stable within a day.

profile.yaml:
    rotations:
      - name: "Spanish practice"
        minutes: 20
        items:
          - "Duolingo: one full unit"
          - "Watch one episode with Spanish subtitles | https://example.com/show"

Each rotation keeps `{last_index, last_used}` under state/history.json
`rotations.<slug>`. On a new day the next item is used; on the same day
(a re-run, or the backup edition after the routine) the same item comes back.
The workout module uses the same mechanism under the key "workout".
"""

import config


def pick_index(hist, key, n, today):
    if n <= 0:
        return None
    st = (hist.get("rotations") or {}).get(key) or {}
    last = st.get("last_index")
    if not isinstance(last, int):
        return 0
    if st.get("last_used") == today.isoformat():
        return last % n
    return (last + 1) % n


def record(hist, key, index, today):
    if index is None:
        return
    hist.setdefault("rotations", {})[key] = {"last_index": index, "last_used": today.isoformat()}


def item_facts(raw):
    text, url = config.split_link(raw)
    return {"text": text, "url": url}


def facts(ctx):
    out = []
    for i, rot in enumerate(config.as_list(config.get(ctx["cfg"], "rotations", []))):
        if not isinstance(rot, dict) or not rot.get("name"):
            ctx["warnings"].append(f"rotations[{i}] needs a name and items, ignored")
            continue
        items = [str(x) for x in config.as_list(rot.get("items")) if str(x).strip()]
        if not items:
            ctx["warnings"].append(f"rotation {rot['name']!r} has no items, ignored")
            continue
        key = config.slug(rot["name"])
        idx = pick_index(ctx["history"], key, len(items), ctx["today"])
        entry = {"key": key, "name": str(rot["name"]), "minutes": rot.get("minutes"), "index": idx}
        entry.update(item_facts(items[idx]))
        if rot.get("note"):
            entry["note"] = str(rot["note"]).strip()
        out.append(entry)
    return out


def save(ctx, results, hist):
    for r in results:
        record(hist, r["key"], r["index"], ctx["today"])
