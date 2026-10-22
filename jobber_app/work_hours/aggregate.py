"""Group Jobber timesheet entries into per-user, per-local-day regular / drive-time seconds."""

from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

# Jobber's BREAK category is unpaid time: never counted as regular or drive time.
EXCLUDED_CATEGORIES = frozenset({"BREAK"})
DEFAULT_CATEGORY = "GENERAL"


def parse_iso(value):
    """Parse a Jobber ISO8601DateTime into an aware UTC datetime."""
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_midnight_utc(day, tz):
    """Start of ``day`` in ``tz``, as an aware UTC datetime."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def split_by_local_day(start, end, tz):
    """
    Yield (local_date, seconds) for the interval [start, end), split at local midnights.

    Works in UTC so DST days count real elapsed time (23h / 25h days).
    """
    cur = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    while cur < end:
        day = cur.astimezone(tz).date()
        seg_end = min(end, local_midnight_utc(day + timedelta(days=1), tz))
        yield day, (seg_end - cur).total_seconds()
        cur = seg_end


def aggregate_entries(entries, tz, drive_categories, window_start, window_end):
    """
    Sum timesheet seconds per (jobber_user_id, local date) for dates in [window_start, window_end).

    Returns (totals, stats): totals maps (user_id, date) -> {"regular": secs, "drive": secs}.
    Running timers are skipped (picked up on a later run once stopped).
    """
    totals = defaultdict(lambda: {"regular": 0.0, "drive": 0.0})
    stats = Counter()
    for entry in entries:
        user_id = ((entry.get("user") or {}).get("id") or "").strip()
        if not user_id:
            stats["skipped_no_user"] += 1
            continue
        if entry.get("ticking"):
            stats["skipped_running"] += 1
            continue
        category = (entry.get("timeSheetCategory") or DEFAULT_CATEGORY).upper()
        if category in EXCLUDED_CATEGORIES:
            stats["skipped_break"] += 1
            continue
        bucket = "drive" if category in drive_categories else "regular"

        start = parse_iso(entry["startAt"])
        if entry.get("endAt"):
            parts = split_by_local_day(start, parse_iso(entry["endAt"]), tz)
        else:
            # Entries without a time range: whole duration on the start date.
            parts = [(start.astimezone(tz).date(), float(entry.get("finalDuration") or 0))]

        for day, seconds in parts:
            if window_start <= day < window_end and seconds > 0:
                totals[(user_id, day)][bucket] += seconds
        stats["counted"] += 1
    return dict(totals), stats


def seconds_to_hours(seconds):
    """Seconds -> Decimal hours with 2 decimals (half-up)."""
    return (Decimal(str(seconds)) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
