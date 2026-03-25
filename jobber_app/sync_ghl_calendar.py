"""
Sync Jobber visits (busy times) to GoHighLevel calendar block slots.

Uses jobber_app.client.get_visits and jobber_app.ghl_calendar_client.
"""
import logging

from decouple import config

from .client import get_visits
from .ghl_calendar_client import (
    create_block_slot,
    delete_calendar_event,
    parse_iso_datetime,
    update_block_slot,
)
from .models import JobberVisitGhlBlockMap

logger = logging.getLogger(__name__)

DEFAULT_TITLE_PREFIX = "Jobber"


def _extract_ghl_event_id(data):
    """Parse event id from various possible GHL response shapes."""
    if not data or not isinstance(data, dict):
        return None
    for key in ("id", "eventId", "_id"):
        if data.get(key):
            return str(data[key])
    ev = data.get("event") or data.get("data") or {}
    if isinstance(ev, dict):
        for key in ("id", "eventId", "_id"):
            if ev.get(key):
                return str(ev[key])
    return None


def sync_jobber_visits_to_ghl_blocks(after_iso, before_iso):
    """
    Fetch Jobber visits in [after_iso, before_iso], upsert GHL block slots, remove stale blocks.

    Returns dict: { created, updated, deleted, skipped, errors: [...] }
    """
    location_id = config("GHL_LOCATION_ID", default=None)
    calendar_id = config("GHL_BOOKING_CALENDAR_ID", default=None)
    if not location_id or not calendar_id:
        return {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "errors": [
                "Set GHL_LOCATION_ID and GHL_BOOKING_CALENDAR_ID in environment "
                "(sub-account location ID and the calendar ID that powers the booking widget)."
            ],
        }

    visits, err = get_visits(after_iso, before_iso)
    if err:
        return {
            "created": 0,
            "updated": 0,
            "deleted": 0,
            "skipped": 0,
            "errors": [err],
        }

    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "errors": []}
    seen_jobber_ids = set()

    for v in visits:
        vid = v.get("id")
        if not vid:
            continue
        seen_jobber_ids.add(str(vid))
        title = (v.get("title") or "").strip()
        block_title = f"{DEFAULT_TITLE_PREFIX}: {title}" if title else DEFAULT_TITLE_PREFIX
        start_raw = v.get("startAt")
        end_raw = v.get("endAt")
        start_dt = parse_iso_datetime(start_raw)
        end_dt = parse_iso_datetime(end_raw)
        if not start_dt or not end_dt:
            stats["skipped"] += 1
            continue
        # GHL expects ISO strings; use Z format
        start_iso = start_dt.isoformat().replace("+00:00", "Z")
        end_iso = end_dt.isoformat().replace("+00:00", "Z")

        existing = JobberVisitGhlBlockMap.objects.filter(jobber_visit_id=str(vid)).first()
        if existing:
            same_time = (
                existing.start_at == start_dt and existing.end_at == end_dt and (existing.title or "") == block_title
            )
            if same_time:
                stats["skipped"] += 1
                continue
            upd, uerr = update_block_slot(
                existing.ghl_event_id,
                location_id,
                calendar_id,
                start_iso,
                end_iso,
                title=block_title,
            )
            if uerr:
                stats["errors"].append(f"update {vid}: {uerr}")
                continue
            existing.start_at = start_dt
            existing.end_at = end_dt
            existing.title = block_title[:500]
            existing.save(update_fields=["start_at", "end_at", "title", "updated_at"])
            stats["updated"] += 1
        else:
            created, cerr = create_block_slot(
                location_id,
                calendar_id,
                start_iso,
                end_iso,
                title=block_title,
            )
            if cerr:
                stats["errors"].append(f"create {vid}: {cerr}")
                continue
            eid = _extract_ghl_event_id(created)
            if not eid:
                stats["errors"].append(f"create {vid}: no event id in GHL response: {created}")
                continue
            JobberVisitGhlBlockMap.objects.create(
                jobber_visit_id=str(vid),
                ghl_event_id=eid,
                start_at=start_dt,
                end_at=end_dt,
                title=block_title[:500],
            )
            stats["created"] += 1

    # Remove GHL blocks for visits not returned in this Jobber query (cancelled / rescheduled out of range).
    after_dt = parse_iso_datetime(after_iso)
    before_dt = parse_iso_datetime(before_iso)
    stale_qs = JobberVisitGhlBlockMap.objects.exclude(jobber_visit_id__in=seen_jobber_ids)
    if after_dt and before_dt:
        stale_qs = stale_qs.filter(start_at__gte=after_dt, start_at__lt=before_dt)

    for row in stale_qs:
        d, derr = delete_calendar_event(row.ghl_event_id)
        if derr:
            stats["errors"].append(f"delete {row.jobber_visit_id}: {derr}")
            continue
        row.delete()
        stats["deleted"] += 1

    return stats
