"""
One-time CSV match: Airtable visits Client → unique GHL contact (exact name keys only).
No Jobber lookup. No GHL API calls.
"""
import csv
import re
from collections import Counter, defaultdict

DEFAULT_TAG = "new client feedback sent"
DEFAULT_VISIT_COUNT_FIELD_ID = "14nLMLzzIPvF65shBM9w"


def normalize_name(value):
    s = str(value or "").strip().lower()
    s = s.replace(".", "")
    s = re.sub(r"\s+", " ", s)
    return s


def csv_has_tag(tags_cell, tag):
    raw = str(tags_cell or "")
    parts = [p.strip() for p in re.split(r"[,;]", raw) if p.strip()]
    needle = tag.strip().lower()
    return any(p.lower() == needle for p in parts)


def _ghl_keys(row):
    name = normalize_name(row.get("Name"))
    first_last = normalize_name(
        f"{row.get('First Name') or ''} {row.get('Last Name') or ''}"
    )
    company = normalize_name(row.get("Company Name"))
    keys = []
    for k in (name, first_last, company):
        if k and k not in keys:
            keys.append(k)
    return keys


def load_visits_counts(visits_path):
    """Exact Client string → row count (blank client ignored)."""
    counts = Counter()
    with open(visits_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            client = (row.get("Client") or "").strip()
            if client:
                counts[client] += 1
    return counts


def load_ghl_index(ghl_path):
    """
    Returns (key → set of GHL IDs, id → meta dict).
    meta: name, tags_cell, location_id
    """
    index = defaultdict(set)
    meta = {}
    with open(ghl_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            gid = (row.get("GHL ID") or "").strip()
            if not gid:
                continue
            if gid not in meta:
                meta[gid] = {
                    "name": (row.get("Name") or "").strip(),
                    "first_name": (row.get("First Name") or "").strip(),
                    "last_name": (row.get("Last Name") or "").strip(),
                    "company": (row.get("Company Name") or "").strip(),
                    "tags_cell": row.get("Tags") or "",
                    "location_id": (row.get("Location ID") or "").strip(),
                }
            for key in _ghl_keys(row):
                index[key].add(gid)
    return index, meta


def match_clients(visit_counts, ghl_index, ghl_meta, tag=DEFAULT_TAG):
    """
    Exact match = exactly one unique GHL ID for the normalized Client string.
    Multiple visit Client strings that resolve to the same GHL ID are merged
    (visit_count summed) — usually double-space name variants.
    """
    exact_rows = []
    multi = []
    unmatched = []

    for client, visit_count in sorted(visit_counts.items(), key=lambda x: x[0].lower()):
        ids = set(ghl_index.get(normalize_name(client), set()))
        if len(ids) == 1:
            gid = next(iter(ids))
            meta = ghl_meta.get(gid) or {}
            exact_rows.append(
                {
                    "client": client,
                    "ghl_id": gid,
                    "visit_count": visit_count,
                    "already_has_tag": csv_has_tag(meta.get("tags_cell"), tag),
                    "ghl_name": meta.get("name") or "",
                    "ghl_company": meta.get("company") or "",
                }
            )
        elif len(ids) == 0:
            unmatched.append({"client": client, "visit_count": visit_count})
        else:
            multi.append(
                {
                    "client": client,
                    "visit_count": visit_count,
                    "ghl_ids": ",".join(sorted(ids)),
                    "match_count": len(ids),
                }
            )

    by_ghl = defaultdict(list)
    for row in exact_rows:
        by_ghl[row["ghl_id"]].append(row)

    would_update = []
    merged = []
    for gid, rows in sorted(by_ghl.items(), key=lambda x: x[1][0]["client"].lower()):
        clients = [r["client"] for r in rows]
        total = sum(r["visit_count"] for r in rows)
        first = rows[0]
        item = {
            "client": " | ".join(clients),
            "ghl_id": gid,
            "visit_count": total,
            "already_has_tag": first["already_has_tag"],
            "ghl_name": first["ghl_name"],
            "ghl_company": first["ghl_company"],
            "matched_client_count": len(rows),
        }
        would_update.append(item)
        if len(rows) > 1:
            merged.append(item)

    return {
        "unique_clients": len(visit_counts),
        "exact_client_strings": len(exact_rows),
        "would_update": would_update,
        "merged_same_ghl_id": merged,
        "multi": multi,
        "unmatched": unmatched,
        "exact_rows": exact_rows,
    }


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
