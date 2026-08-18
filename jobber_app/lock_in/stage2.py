"""Stage 2 — first recurring VISIT_COMPLETE → confirm or expire + SMS."""

import logging

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import ghl_sms, hub_client
from .matching import format_confirm_date, is_internal_client, title_is_first_cleaning

logger = logging.getLogger(__name__)


def _confirm_sms(*, client_name, amount, position, confirm_date):
    return (
        "🎉 Congratulations!\n\n"
        f"Your lock-in bonus for {client_name} has been confirmed.\n\n"
        f"Bonus Amount: ${amount}\n\n"
        f"Position: {position}\n\n"
        f"Confirmation Date: {confirm_date}\n\n"
        "Status: Confirmed\n\n"
        "Great job helping convert this client into a recurring customer!"
    )


def _parse_expires(pending):
    raw = pending.get("eligibility_expires_at") or pending.get("quote_sent_at")
    return parse_datetime(str(raw)) if raw else None


def process_visit_complete_confirm(visit, *, upserted=None):
    """
    visit: Jobber visit dict (client, job, title, id, startAt).
    Make searched pending by client_id only; we prefer matching recurring job_id.
    """
    client = (visit or {}).get("client") or {}
    client_id = str(client.get("id") or "")
    client_name = client.get("name") or ""
    if not client_id:
        return {"ok": True, "skipped": True, "reason": "no_client"}
    if is_internal_client(client_name):
        return {"ok": True, "skipped": True, "reason": "internal_client"}

    title = visit.get("title") or ""
    if title_is_first_cleaning(title):
        return {"ok": True, "skipped": True, "reason": "first_cleaning_visit"}

    job = visit.get("job") or {}
    job_id = str(job.get("id") or "")
    job_type = str(job.get("jobType") or "")
    visit_id = str(visit.get("id") or "")

    try:
        looked = hub_client.lookup_pending(client_id, job_id or None)
    except hub_client.HubLockInError as exc:
        return {"ok": False, "error": str(exc)}

    pending = (looked or {}).get("pending")
    if not pending:
        return {"ok": True, "skipped": True, "reason": "no_open_pending"}

    originals = {str(x) for x in (pending.get("original_visit_ids") or []) if x}
    if visit_id and visit_id in originals:
        return {"ok": True, "skipped": True, "reason": "original_first_clean_visit"}

    recurring_id = pending.get("job_id") or ""
    if recurring_id and job_id and recurring_id != job_id:
        if job_type.upper() == "ONE_OFF":
            return {"ok": True, "skipped": True, "reason": "job_mismatch_one_off"}

    if pending.get("locked_in") or pending.get("status") == "confirmed":
        return {"ok": True, "skipped": True, "reason": "already_confirmed"}

    now = timezone.now()
    expires = _parse_expires(pending)
    if expires and now > expires:
        try:
            hub_client.expire_pending(pending["id"])
        except hub_client.HubLockInError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "expired": True, "pending_id": pending.get("id")}

    visit_at = visit.get("startAt")
    try:
        confirmed = hub_client.confirm_pending(
            pending["id"], visit_id=visit_id, visit_at=visit_at
        )
    except hub_client.HubLockInError as exc:
        return {"ok": False, "error": str(exc)}

    pending = (confirmed or {}).get("pending") or pending
    confirm_label = format_confirm_date(parse_datetime(str(visit_at)) if visit_at else now)
    sms_results = []
    for bonus in pending.get("bonuses") or []:
        sms_results.append(
            _sms_confirm(bonus, pending.get("client_name") or client_name, confirm_label)
        )
    return {
        "ok": True,
        "confirmed": True,
        "pending_id": pending.get("id"),
        "sms": sms_results,
    }


def _sms_confirm(bonus, client_name, confirm_label):
    tech = bonus.get("technician") or {}
    amount = bonus.get("amount") or "0"
    try:
        if float(amount) <= 0:
            return {"skipped": True, "reason": "amount_zero", "technician_id": tech.get("id")}
    except (TypeError, ValueError):
        pass

    cid, err = ghl_sms.resolve_staff_contact(
        phone=tech.get("phone") or "",
        name=tech.get("name") or "",
        existing_ghl_id=tech.get("ghl_id") or "",
    )
    if err:
        logger.warning("Lock-in confirm SMS contact: %s", err)
        return {"ok": False, "error": err, "technician_id": tech.get("id")}
    if cid and cid != (tech.get("ghl_id") or "") and tech.get("id"):
        try:
            hub_client.set_user_ghl_id(tech["id"], cid)
        except hub_client.HubLockInError as exc:
            logger.warning("Lock-in store ghl_id: %s", exc)

    msg = _confirm_sms(
        client_name=client_name,
        amount=amount,
        position=bonus.get("position_snapshot") or tech.get("position") or "",
        confirm_date=confirm_label,
    )
    _, serr = ghl_sms.send_sms(contact_id=cid, to_number=tech.get("phone") or "", message=msg)
    if serr:
        logger.warning("Lock-in confirm SMS send: %s", serr)
        return {"ok": False, "error": serr, "technician_id": tech.get("id")}
    try:
        hub_client.mark_bonus_sms(bonus["id"], confirmation_sms_sent=True)
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in mark confirm SMS: %s", exc)
    return {"ok": True, "technician_id": tech.get("id")}
