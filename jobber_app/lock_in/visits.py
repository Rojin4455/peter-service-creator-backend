"""VISIT_COMPLETE: persist visit assignees in Hub, then Stage 2 confirm."""

import logging

from . import hub_client, jobber, stage2
from .matching import assigned_user_ids, is_internal_client

logger = logging.getLogger(__name__)


def process_visit_complete(visit_id):
    visit_id = str(visit_id or "").strip()
    if not visit_id:
        return {"ok": False, "error": "missing visit id"}

    visit, err = jobber.get_visit_lock_in(visit_id)
    if err:
        return {"ok": False, "error": err}
    if not visit:
        return {"ok": False, "skipped": True, "reason": "visit_not_found"}

    client = visit.get("client") or {}
    client_name = client.get("name") or ""
    if is_internal_client(client_name):
        return {"ok": True, "skipped": True, "reason": "internal_client"}

    job = visit.get("job") or {}
    upserted = None
    try:
        upserted = hub_client.upsert_visit(
            {
                "jobber_visit_id": visit.get("id") or visit_id,
                "title": visit.get("title") or "",
                "client_id": client.get("id") or "",
                "client_name": client_name,
                "job_id": job.get("id") or "",
                "job_type": job.get("jobType") or "",
                "start_at": visit.get("startAt"),
                "assignee_jobber_ids": assigned_user_ids(visit),
            }
        )
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in visit upsert failed visit=%s: %s", visit_id, exc)
        return {"ok": False, "error": str(exc)}

    confirm = stage2.process_visit_complete_confirm(visit, upserted=upserted)
    return {"ok": True, "visit_upsert": upserted, "confirm": confirm}
