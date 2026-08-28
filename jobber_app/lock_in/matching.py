"""Pure helpers for lock-in job/title matching."""

from datetime import datetime

from django.utils.dateparse import parse_datetime
from django.utils import timezone

from .constants import JOB_TITLE_FIRST_CLEAN, JOB_TITLE_RECURRING, INTERNAL_CLIENT_NAME


def _norm(s):
    return " ".join(str(s or "").lower().split())


def is_internal_client(name):
    return _norm(name) == _norm(INTERNAL_CLIENT_NAME)


def title_is_first_cleaning(title):
    return JOB_TITLE_FIRST_CLEAN in _norm(title)


def title_is_lock_in_job(title):
    t = _norm(title)
    if JOB_TITLE_FIRST_CLEAN in t:
        return True
    return recurring_frequency_from_title(title) is not None


def recurring_frequency_from_title(title):
    t = _norm(title)
    for needle, label in JOB_TITLE_RECURRING:
        if needle in t:
            return label
    return None


def classify_jobs(jobs):
    first_clean = []
    recurring = []
    for job in jobs or []:
        title = (job or {}).get("title") or ""
        if not title_is_lock_in_job(title):
            continue
        if title_is_first_cleaning(title) and not recurring_frequency_from_title(title):
            first_clean.append(job)
        elif recurring_frequency_from_title(title):
            recurring.append(job)
        else:
            first_clean.append(job)
    return first_clean, recurring


def pick_frequency(recurring_jobs):
    for job in recurring_jobs or []:
        freq = recurring_frequency_from_title((job or {}).get("title"))
        if freq:
            return freq
    return ""


def connection_nodes(conn):
    conn = conn or {}
    nodes = conn.get("nodes")
    if nodes:
        return list(nodes)
    return [e.get("node") for e in (conn.get("edges") or []) if e.get("node")]


def quote_line_item_names(quote):
    """Product names only — never descriptions."""
    names = []
    for node in connection_nodes((quote or {}).get("lineItems")):
        name = (node or {}).get("name") or ""
        if name:
            names.append(name)
    return names


def frequency_from_texts(texts):
    for text in texts or []:
        freq = recurring_frequency_from_title(text)
        if freq:
            return freq
    return ""


def frequency_from_quote(quote):
    title = (quote or {}).get("title") or ""
    return frequency_from_texts([title] + quote_line_item_names(quote))


def job_looks_recurring(job):
    job = job or {}
    if recurring_frequency_from_title(job.get("title") or ""):
        return True
    return str(job.get("jobType") or "").upper() == "RECURRING"


def parse_iso(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return parse_datetime(str(value))


def format_confirm_date(dt):
    if not dt:
        return "Currently Unknown"
    if timezone.is_naive(dt):
        return dt.strftime("%Y-%m-%d")
    return timezone.localtime(dt).strftime("%Y-%m-%d")


def assigned_user_ids(visit):
    nodes = ((visit or {}).get("assignedUsers") or {}).get("nodes") or []
    out = []
    for n in nodes:
        uid = (n or {}).get("id")
        if uid:
            out.append(str(uid))
    return out
