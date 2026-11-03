"""
Nightly sync: Jobber visits → Hub (POST /api/internal/visits/upsert/) for contractor pay.

Sends every visit dated in the last N Toronto days (default 30) plus visits on invoices updated in
that period, re-sending each night so the Hub always holds current values (it carries differences
on paid weeks into the next open week). Visits we sent before that Jobber no longer has are re-sent
once with status "deleted" and 0.00 amounts.

Off until VISITS_SYNC_ENABLED is true (the Hub endpoint must be live first); --dry-run always works.
"""

import logging
from datetime import date, timedelta

from decouple import config
from django.db import transaction
from django.utils import timezone as dj_timezone

from jobber_app.models import VisitSyncState
from jobber_app.work_hours import hub_client
from jobber_app.work_hours.aggregate import local_midnight_utc
from jobber_app.work_hours.sync import _invalid_indexes, work_hours_timezone

from . import jobber
from .amounts import build_entry, deleted_entry

logger = logging.getLogger(__name__)

UPSERT_PATH = "/api/internal/visits/upsert/"
BATCH_SIZE = 500  # Hub accepts up to 1000 entries per request


def visits_sync_enabled():
    return config("VISITS_SYNC_ENABLED", default=False, cast=bool)


def lookback_days():
    return int(config("VISITS_LOOKBACK_DAYS", default=30))


def _collect_visits(window_start, window_end, now, days, tz):
    """
    Returns (visits by id, deleted VisitSyncState rows, invoice weights by invoice id).
    Raises jobber.JobberFetchError on any read failure, so nothing is sent or marked deleted.
    """
    by_id = {
        v["id"]: v
        for v in jobber.fetch_window_visits(
            local_midnight_utc(window_start, tz), local_midnight_utc(window_end, tz)
        )
    }
    window_ids = set(by_id)

    for visit_id in jobber.fetch_updated_invoice_visit_ids(now - timedelta(days=days), now):
        if visit_id not in by_id:
            visit = jobber.fetch_visit(visit_id)
            if visit:
                by_id[visit_id] = visit

    # A visit missing from the window may have been rescheduled, not deleted: check before deleting.
    deleted = []
    previously_sent = VisitSyncState.objects.filter(
        date__gte=window_start, date__lt=window_end
    ).exclude(status="deleted")
    for state in previously_sent:
        if state.jobber_visit_id in by_id:
            continue
        visit = jobber.fetch_visit(state.jobber_visit_id)
        if visit:
            by_id[visit["id"]] = visit
        else:
            deleted.append(state)

    weights = {}
    for visit in by_id.values():
        invoice = visit.get("invoice") or {}
        if ((invoice.get("visits") or {}).get("totalCount") or 0) > 1 and invoice["id"] not in weights:
            weights[invoice["id"]] = jobber.fetch_invoice_line_weights(invoice["id"])

    logger.info(
        "Visits sync: %s in window, %s more from updated invoices/reschedules, %s deleted",
        len(window_ids), len(by_id) - len(window_ids), len(deleted),
    )
    return by_id, deleted, weights


def _record_sent(entries):
    with transaction.atomic():
        for entry in entries:
            VisitSyncState.objects.update_or_create(
                jobber_visit_id=entry["jobber_visit_id"],
                defaults={
                    "date": date.fromisoformat(entry["date"]) if entry.get("date") else None,
                    "status": entry.get("status") or "",
                    "payload": entry,
                },
            )


def sync_visits(*, days=None, dry_run=False, now=None):
    """
    Build and (unless dry_run) send visit rows to the Hub.

    Returns a JSON-serialisable summary with "ok" and, on failure, "error".
    """
    days = days or lookback_days()
    summary = {"ok": False, "dry_run": dry_run}
    if not dry_run and not visits_sync_enabled():
        summary.update(ok=True, skipped="VISITS_SYNC_ENABLED is off; nothing sent")
        logger.info("Visits sync skipped: VISITS_SYNC_ENABLED is off")
        return summary

    tz = work_hours_timezone()
    now = now or dj_timezone.now()
    today = now.astimezone(tz).date()
    window_start, window_end = today - timedelta(days=days), today + timedelta(days=1)
    summary.update(window_start=window_start.isoformat(), window_end_exclusive=window_end.isoformat())

    try:
        by_id, deleted, weights = _collect_visits(window_start, window_end, now, days, tz)
    except jobber.JobberFetchError as exc:
        logger.error("Visits sync: Jobber fetch failed, nothing sent: %s", exc)
        summary["error"] = f"Jobber fetch failed: {exc}"
        return summary

    entries = [
        build_entry(v, tz, weights.get((v.get("invoice") or {}).get("id")))
        for _, v in sorted(by_id.items())
    ]
    entries += [deleted_entry(state.jobber_visit_id, state.payload) for state in deleted]

    summary.update(
        visits=len(entries),
        deleted=len(deleted),
        by_amount_rule={
            rule: sum(1 for e in entries if e.get("amount_rule") == rule and e["status"] != "deleted")
            for rule in ("invoice", "invoice_share", "estimate", "job_price")
        },
        needs_review=sum(1 for e in entries if e.get("amount_needs_review")),
        internal=sum(1 for e in entries if e.get("internal")),
    )
    if dry_run:
        summary["ok"] = True
        summary["sample"] = entries[:3]
        return summary

    saved = invalid_count = 0
    unknown_users = set()
    invalid_examples = []
    for start in range(0, len(entries), BATCH_SIZE):
        batch = entries[start:start + BATCH_SIZE]
        try:
            result = hub_client.upsert_entries(UPSERT_PATH, batch) or {}
        except hub_client.HubWorkHoursError as exc:
            logger.error("Visits sync: Hub upsert failed at batch offset %s: %s", start, exc)
            summary.update(saved=saved, invalid=invalid_count, error=f"Hub upsert failed: {exc}")
            return summary
        invalid = result.get("invalid") or []
        # Hub response: {"saved", "unknown_user_ids", "invalid"}. Visits with unknown users are
        # still saved by the Hub, so they're reported, not treated as errors.
        unknown_users |= set(map(str, result.get("unknown_user_ids") or []))
        if invalid:
            logger.warning("Hub rejected %s invalid visit rows: %s", len(invalid), invalid)
            invalid_examples.extend(
                {**item, "index": item["index"] + start}
                if isinstance(item, dict) and isinstance(item.get("index"), int) else item
                for item in invalid[: max(0, 5 - len(invalid_examples))]
            )
        bad = _invalid_indexes(invalid)
        _record_sent([e for i, e in enumerate(batch) if i not in bad])
        saved += int(result.get("saved") or 0)
        invalid_count += len(invalid)

    if unknown_users:
        logger.warning("Hub doesn't know %s Jobber users on visits: %s", len(unknown_users), sorted(unknown_users))
    summary.update(
        ok=True, saved=saved, unknown_user_ids=sorted(unknown_users),
        invalid=invalid_count, invalid_examples=invalid_examples,
    )
    logger.info("Visits sync done: %s", summary)
    return summary
