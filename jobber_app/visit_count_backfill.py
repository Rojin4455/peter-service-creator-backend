"""
One-time CSV match: Airtable visits Client → unique GHL contact (exact name keys only).
No Jobber lookup. No GHL API calls.
"""
import csv
import re
import time
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher

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


def ghl_api_contact_keys(contact):
    """Normalized Name / First+Last / Company from a live GHL contact dict."""
    if not isinstance(contact, dict):
        return []
    name = normalize_name(contact.get("name") or "")
    first_last = normalize_name(
        f"{contact.get('firstName') or ''} {contact.get('lastName') or ''}"
    )
    company = normalize_name(
        contact.get("companyName") or contact.get("company") or ""
    )
    keys = []
    for k in (name, first_last, company):
        if k and k not in keys:
            keys.append(k)
    return keys


def exact_ghl_ids_for_client(client, contacts):
    key = normalize_name(client)
    ids = set()
    meta = {}
    if not key:
        return ids, meta
    for c in contacts or []:
        if not isinstance(c, dict):
            continue
        gid = str(c.get("id") or "").strip()
        if not gid:
            continue
        if key in ghl_api_contact_keys(c):
            ids.add(gid)
            meta[gid] = c
    return ids, meta


def live_match_unmatched(unmatched_rows, search_fn, *, tag=DEFAULT_TAG, sleep_s=0.2, on_progress=None):
    """
    search_fn(query) → (list of contact dicts, error or None)
    Exact unique GHL ID only, same name-key rules as CSV matching.
    """
    exact = []
    multi = []
    still = []
    errors = []
    total = len(unmatched_rows)
    for i, row in enumerate(unmatched_rows, start=1):
        client = row.get("client") or ""
        visit_count = row.get("visit_count") or 0
        if on_progress:
            on_progress(i, total, client)
        contacts, err = search_fn(client)
        if err:
            errors.append({**row, "error": err})
            still.append({**row, "reason": "search_error"})
            if sleep_s:
                time.sleep(sleep_s)
            continue
        ids, meta = exact_ghl_ids_for_client(client, contacts)
        if len(ids) == 1:
            gid = next(iter(ids))
            c = meta.get(gid) or {}
            tags = c.get("tags") or []
            already = False
            if isinstance(tags, list):
                already = any(str(t).strip().lower() == tag.lower() for t in tags)
            elif isinstance(tags, str):
                already = csv_has_tag(tags, tag)
            exact.append(
                {
                    "client": client,
                    "ghl_id": gid,
                    "visit_count": visit_count,
                    "already_has_tag": already,
                    "ghl_name": (c.get("name") or "").strip()
                    or f"{c.get('firstName') or ''} {c.get('lastName') or ''}".strip(),
                    "ghl_company": (c.get("companyName") or c.get("company") or "").strip(),
                    "matched_client_count": 1,
                    "source": "live_ghl",
                }
            )
        elif len(ids) == 0:
            still.append({**row, "reason": "unmatched", "search_hits": len(contacts or [])})
        else:
            multi.append(
                {
                    **row,
                    "ghl_ids": ",".join(sorted(ids)),
                    "match_count": len(ids),
                }
            )
        if sleep_s and i < total:
            time.sleep(sleep_s)

    by_ghl = defaultdict(list)
    for row in exact:
        by_ghl[row["ghl_id"]].append(row)
    would_update = []
    merged = []
    for gid, rows in sorted(by_ghl.items(), key=lambda x: x[1][0]["client"].lower()):
        clients = [r["client"] for r in rows]
        total_visits = sum(int(r["visit_count"]) for r in rows)
        first = rows[0]
        item = {
            **first,
            "client": " | ".join(clients),
            "visit_count": total_visits,
            "matched_client_count": len(rows),
        }
        would_update.append(item)
        if len(rows) > 1:
            merged.append(item)

    return {
        "would_update": would_update,
        "merged_same_ghl_id": merged,
        "multi": multi,
        "still_unmatched": still,
        "errors": errors,
        "exact_rows": exact,
    }


TITLES = {"mr", "mrs", "ms", "miss", "dr", "mme", "mlle", "mister", "madame"}
PARTICLES = {"de", "di", "da", "del", "della", "van", "von", "le", "la", "du", "des", "st", "ste"}
INTERNAL_FOLDED = {"lockin test client"}
FUZZY_MIN_SCORE = 86
FUZZY_GAP = 12


def strip_accents(value):
    s = unicodedata.normalize("NFD", str(value or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def fold_name(value):
    s = strip_accents(value).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def strip_titles_folded(folded):
    toks = [t for t in (folded or "").split() if t]
    while toks and toks[0] in TITLES:
        toks = toks[1:]
    return " ".join(toks)


def collapse_particles(toks):
    out = []
    i = 0
    toks = list(toks or [])
    while i < len(toks):
        if i < len(toks) - 1 and toks[i] in PARTICLES:
            out.append(toks[i] + toks[i + 1])
            i += 2
        else:
            out.append(toks[i])
            i += 1
    return out


def name_tokens(value):
    folded = strip_titles_folded(fold_name(value))
    raw = [t for t in folded.split() if t and t != "and"]
    return collapse_particles(raw)


def ghl_display_name(contact):
    if not isinstance(contact, dict):
        return ""
    n = (contact.get("name") or "").strip()
    if n:
        return n
    return f"{contact.get('firstName') or ''} {contact.get('lastName') or ''}".strip()


def ghl_folded_keys(contact):
    keys = []
    company = contact.get("companyName") or contact.get("company") or ""
    first_last = f"{contact.get('firstName') or ''} {contact.get('lastName') or ''}"
    for raw in (ghl_display_name(contact), first_last, company):
        k = strip_titles_folded(fold_name(raw))
        if k and k not in keys:
            keys.append(k)
    return keys


def _first_close(a, b):
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a.startswith(b) or b.startswith(a):
        if min(len(a), len(b)) >= 3:
            return 0.92
    return SequenceMatcher(None, a, b).ratio()


def score_client_to_contact(client, contact):
    """Return (score 0-100, reason)."""
    cf = strip_titles_folded(fold_name(client))
    ctoks = name_tokens(client)
    best = 0
    reason = "no_overlap"
    for key in ghl_folded_keys(contact):
        ktoks = collapse_particles([t for t in key.split() if t and t != "and"])
        if not key:
            continue
        if key == cf:
            return 100, "folded_exact"
        if ctoks and ktoks and set(ctoks) == set(ktoks):
            return 98, "token_set_equal"
        full = SequenceMatcher(None, cf, key).ratio()
        if full >= 0.93:
            sc = int(round(full * 100))
            if sc > best:
                best, reason = sc, "full_string_close"
        if len(ctoks) >= 2 and len(ktoks) >= 2:
            last_c, last_k = ctoks[-1], ktoks[-1]
            first_c, first_k = ctoks[0], ktoks[0]
            last_r = SequenceMatcher(None, last_c, last_k).ratio()
            first_r = _first_close(first_c, first_k)
            if last_c == last_k and first_r >= 0.8:
                sc = 94 if first_r >= 0.92 else 90
                if sc > best:
                    best, reason = sc, "same_last_close_first"
            elif last_r >= 0.84 and first_r >= 0.84:
                sc = 88
                if sc > best:
                    best, reason = sc, "close_first_and_last"
            # "Carlos and Dora Valenzuela" vs "Carlos Valenzuela"
            if last_c == last_k and ktoks[0] in ctoks and len(ktoks[0]) >= 3:
                sc = 91
                if sc > best:
                    best, reason = sc, "shared_last_and_first_token"
        # company: "Melkonian Finance" vs name "Alex Melkonian"
        if ctoks and ktoks:
            overlap = set(ctoks) & set(ktoks)
            distinctive = {t for t in overlap if len(t) >= 6}
            if distinctive and (ktoks[-1] in distinctive or ctoks[0] in distinctive):
                sc = 80
                if sc > best:
                    best, reason = sc, "shared_distinctive_token"
    return best, reason


def fuzzy_search_queries(client):
    """Queries to send to GHL search (original + ASCII + no title + last token)."""
    orig = str(client or "").strip()
    qs = []

    def add(q):
        q = " ".join(str(q or "").split())
        if q and q.lower() not in {x.lower() for x in qs}:
            qs.append(q)

    add(orig)
    no_title = re.sub(
        r"^(mr|mrs|ms|miss|dr|mme|mlle)\.?\s+",
        "",
        orig,
        flags=re.IGNORECASE,
    )
    add(no_title)
    add(strip_accents(no_title))
    add(no_title.replace("-", " "))
    toks = name_tokens(orig)
    if len(toks) >= 2:
        add(f"{toks[0]} {toks[-1]}")
    if toks:
        last = toks[-1]
        if len(last) >= 5:
            add(last)
        if len(toks[0]) >= 5 and toks[0] != last:
            add(toks[0])
    return qs


def pick_unique_fuzzy(client, contacts):
    scored = []
    seen = set()
    for c in contacts or []:
        if not isinstance(c, dict):
            continue
        gid = str(c.get("id") or "").strip()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        sc, reason = score_client_to_contact(client, c)
        scored.append((sc, reason, c))
    scored.sort(key=lambda x: (-x[0], x[2].get("id") or ""))
    if not scored:
        return None, [], "no_candidates"
    top_sc, top_reason, top_c = scored[0]
    second_sc = scored[1][0] if len(scored) > 1 else 0
    if top_sc < FUZZY_MIN_SCORE:
        return None, scored[:5], f"best_score_{top_sc}"
    if second_sc and (top_sc - second_sc) < FUZZY_GAP:
        return None, scored[:5], f"ambiguous_{top_sc}_{second_sc}"
    return (top_c, top_sc, top_reason), scored[:5], None


def fuzzy_match_unmatched(unmatched_rows, search_fn, *, tag=DEFAULT_TAG, sleep_s=0.15, on_progress=None):
    """
    Broader live GHL match: accents, titles, particles, small typos.
    Unique winner only.
    search_fn(query) → (list of contacts, error)
    """
    exact = []
    multi = []
    still = []
    errors = []
    skipped = []
    total = len(unmatched_rows)
    for i, row in enumerate(unmatched_rows, start=1):
        client = row.get("client") or ""
        visit_count = row.get("visit_count") or 0
        if on_progress:
            on_progress(i, total, client)
        if fold_name(client) in INTERNAL_FOLDED:
            skipped.append({**row, "reason": "internal_test"})
            continue
        pooled = []
        last_err = None
        for qi, q in enumerate(fuzzy_search_queries(client)):
            contacts, err = search_fn(q)
            if err:
                last_err = err
            else:
                pooled.extend(contacts or [])
            if sleep_s:
                time.sleep(sleep_s)
        if last_err and not pooled:
            errors.append({**row, "error": last_err})
            still.append({**row, "reason": "search_error"})
            continue
        picked, ranked, reject = pick_unique_fuzzy(client, pooled)
        if picked:
            contact, sc, reason = picked
            gid = str(contact.get("id") or "").strip()
            tags = contact.get("tags") or []
            already = False
            if isinstance(tags, list):
                already = any(str(t).strip().lower() == tag.lower() for t in tags)
            elif isinstance(tags, str):
                already = csv_has_tag(tags, tag)
            exact.append(
                {
                    "client": client,
                    "ghl_id": gid,
                    "visit_count": visit_count,
                    "already_has_tag": already,
                    "ghl_name": ghl_display_name(contact),
                    "ghl_company": (contact.get("companyName") or contact.get("company") or "").strip(),
                    "matched_client_count": 1,
                    "source": "fuzzy_ghl",
                    "match_reason": reason,
                    "match_score": sc,
                }
            )
        elif reject and str(reject).startswith("ambiguous"):
            ids = []
            for sc, reason, c in ranked[:3]:
                if sc >= FUZZY_MIN_SCORE - 10:
                    ids.append(f"{c.get('id')}:{ghl_display_name(c)}:{sc}")
            multi.append(
                {
                    **row,
                    "reason": reject,
                    "candidates": " | ".join(ids),
                }
            )
        else:
            top = ""
            if ranked:
                sc, reason, c = ranked[0]
                top = f"{ghl_display_name(c)} ({sc} {reason})"
            still.append(
                {
                    **row,
                    "reason": reject or "unmatched",
                    "search_hits": len({str(c.get('id')) for c in pooled if c.get('id')}),
                    "top_candidate": top,
                }
            )

    by_ghl = defaultdict(list)
    for row in exact:
        by_ghl[row["ghl_id"]].append(row)
    would_update = []
    merged = []
    for gid, rows in sorted(by_ghl.items(), key=lambda x: x[1][0]["client"].lower()):
        clients = [r["client"] for r in rows]
        names = []
        for r in rows:
            n = r.get("ghl_name") or ""
            if n and n not in names:
                names.append(n)
        total_visits = sum(int(r["visit_count"]) for r in rows)
        first = rows[0]
        item = {
            **first,
            "client": " | ".join(clients),
            "original_clients": " | ".join(clients),
            "ghl_name": names[0] if names else first.get("ghl_name") or "",
            "visit_count": total_visits,
            "matched_client_count": len(rows),
        }
        would_update.append(item)
        if len(rows) > 1:
            merged.append(item)

    return {
        "would_update": would_update,
        "merged_same_ghl_id": merged,
        "multi": multi,
        "still_unmatched": still,
        "errors": errors,
        "skipped": skipped,
        "exact_rows": exact,
    }


def contact_visit_count(contact, field_id):
    if not isinstance(contact, dict):
        return 0
    for cf in contact.get("customFields") or []:
        if not isinstance(cf, dict):
            continue
        if str(cf.get("id") or "") != str(field_id):
            continue
        raw = cf.get("value")
        if raw is None:
            raw = cf.get("field_value")
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return 0
    return 0


def write_csv(path, rows, fieldnames):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
