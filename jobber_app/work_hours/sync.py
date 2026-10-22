"""
Nightly sync: Jobber timesheets → Hub work hours.

Re-sends every user-day in the lookback window (the Hub overwrites each day), and re-sends
0.00 for user-days we sent before whose Jobber entries have since been deleted.
Overtime is calculated by the Hub, not here.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from decouple import config
from django.db import transaction
from django.utils import timezone as dj_timezone

from jobber_app.models import WorkHoursSentDay

from . import hub_client, jobber
from .aggregate import aggregate_entries, local_midnight_utc, seconds_to_hours

logger = logging.getLogger(__name__)

BATCH_SIZE = 500  # Hub accepts up to 1000 entries per request
MAX_DAY_HOURS = Decimal("24.00")  # Hub rejects > 24 per field
ZERO_HOURS = Decimal("0.00")
SOURCE = "jobber"


def drive_time_categories():
    raw = config("JOBBER_DRIVE_TIME_CATEGORIES", default="DRIVING") or "DRIVING"
    return frozenset(c.strip().upper() for c in raw.split(",") if c.strip())


def work_hours_timezone():
    return ZoneInfo(config("WORK_HOURS_TIMEZONE", default="America/Toronto") or "America/Toronto")


def lookback_days():
    return int(config("WORK_HOURS_LOOKBACK_DAYS", default=14))


def _hours(seconds, user_id, day):
    hours = seconds_to_hours(seconds)
    if hours > MAX_DAY_HOURS:
        logger.warning(
            "Work hours %s for user=%s date=%s exceed 24; capping (overlapping timers?)",
            hours, user_id, day,
        )
        hours = MAX_DAY_HOURS
    return hours


def _payload(row):
    user_id, day, regular, drive = row
    return {
        "jobber_user_id": user_id,
        "date": day.isoformat(),
        "regular_hours": str(regular),
        "drive_time_hours": str(drive),
        "source": SOURCE,
    }


def _invalid_indexes(invalid):
    """Hub "invalid" lists bad rows by index (ints, or dicts with an "index" key)."""
    out = set()
    for item in invalid or []:
        if isinstance(item, int):
            out.add(item)
        elif isinstance(item, dict) and isinstance(item.get("index"), int):
            out.add(item["index"])
    return out


def _record_sent(rows):
    with transaction.atomic():
        for user_id, day, regular, drive in rows:
            WorkHoursSentDay.objects.update_or_create(
                jobber_user_id=user_id,
                date=day,
                defaults={"regular_hours": regular, "drive_time_hours": drive},
            )


def sync_work_hours(*, days=None, dry_run=False, now=None):
    """
    Read Jobber timesheets for the last ``days`` local days (ending yesterday) and upsert them to the Hub.

    Returns a JSON-serialisable summary dict with "ok" and, on failure, "error".
    A failed Jobber fetch sends nothing, so days are never zeroed because of an API error.
    """
    tz = work_hours_timezone()
    days = days or lookback_days()
    today = (now or dj_timezone.now()).astimezone(tz).date()
    window_start, window_end = today - timedelta(days=days), today
    summary = {
        "ok": False,
        "dry_run": dry_run,
        "window_start": window_start.isoformat(),
        "window_end_exclusive": window_end.isoformat(),
    }

    # One extra day back so entries crossing midnight into the window are included.
    entries, err = jobber.fetch_time_sheet_entries(
        local_midnight_utc(window_start - timedelta(days=1), tz),
        local_midnight_utc(window_end, tz),
    )
    if err:
        logger.error("Work hours sync: Jobber fetch failed, nothing sent: %s", err)
        summary["error"] = f"Jobber fetch failed: {err}"
        return summary

    totals, stats = aggregate_entries(entries, tz, drive_time_categories(), window_start, window_end)
    rows = [
        (user_id, day, _hours(t["regular"], user_id, day), _hours(t["drive"], user_id, day))
        for (user_id, day), t in sorted(totals.items())
    ]
    previously_sent = (
        WorkHoursSentDay.objects.filter(date__gte=window_start, date__lt=window_end)
        .exclude(regular_hours=0, drive_time_hours=0)
        .values_list("jobber_user_id", "date")
    )
    zeroed = sorted(key for key in previously_sent if key not in totals)
    rows.extend((user_id, day, ZERO_HOURS, ZERO_HOURS) for user_id, day in zeroed)

    summary.update(
        entries_fetched=len(entries),
        entry_stats=dict(stats),
        users=len({r[0] for r in rows}),
        days_to_send=len(rows),
        zeroed_days=len(zeroed),
    )
    if dry_run:
        summary["ok"] = True
        summary["sample"] = [_payload(r) for r in rows[:5]]
        return summary

    saved = skipped = invalid_count = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        try:
            result = hub_client.upsert_work_hours([_payload(r) for r in batch]) or {}
        except hub_client.HubWorkHoursError as exc:
            logger.error("Work hours sync: Hub upsert failed at batch offset %s: %s", start, exc)
            summary.update(saved=saved, skipped=skipped, invalid=invalid_count)
            summary["error"] = f"Hub upsert failed: {exc}"
            return summary

        skipped_ids = result.get("skipped_ids") or []
        invalid = result.get("invalid") or []
        if skipped_ids:
            logger.warning(
                "Hub skipped %s work-hours rows for unknown Jobber users: %s",
                len(skipped_ids), sorted(set(skipped_ids)),
            )
        if invalid:
            logger.warning("Hub rejected %s invalid work-hours rows: %s", len(invalid), invalid)
        bad = _invalid_indexes(invalid)
        _record_sent([row for i, row in enumerate(batch) if i not in bad])

        saved += int(result.get("saved") or 0)
        skipped += int(result.get("skipped") or len(skipped_ids))
        invalid_count += len(invalid)

    summary.update(ok=True, saved=saved, skipped=skipped, invalid=invalid_count)
    logger.info("Work hours sync done: %s", summary)
    return summary
