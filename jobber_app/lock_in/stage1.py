"""Stage 1 — QUOTE_APPROVED → pending lock-in + potential SMS."""

import logging

from . import ghl_sms, hub_client, jobber
from .matching import (
    assigned_user_ids,
    classify_jobs,
    format_confirm_date,
    parse_iso,
    pick_frequency,
    title_is_first_cleaning,
)

logger = logging.getLogger(__name__)


def _potential_sms(*, client_name, amount, frequency, confirm_date):
    return (
        "🎉 Congratulations!\n\n"
        f"{client_name} has approved a quote for recurring cleaning services.\n\n"
        f"Potential Earnings: ${amount}\n\n"
        f"Frequency: {frequency or 'Currently Unknown'}\n\n"
        f"Confirmation Date: {confirm_date}\n\n"
        "Status: In Process\n\n"
        "Your lock-in bonus will be confirmed once the client's first recurring "
        "cleaning visit has been successfully completed."
    )


def _collect_techs_from_hub_rows(rows, *, first_clean_only=False):
    techs = []
    seen = set()
    matched_visit_ids = []
    for row in rows or []:
        title = (row or {}).get("title") or ""
        if first_clean_only and not title_is_first_cleaning(title):
            continue
        vid = row.get("jobber_visit_id")
        if vid:
            matched_visit_ids.append(str(vid))
        for t in row.get("technicians") or []:
            jid = (t or {}).get("jobber_id")
            if jid and jid not in seen:
                seen.add(jid)
                techs.append(str(jid))
    return techs, matched_visit_ids


def _tech_ids_from_hub_visits(visit_ids):
    if not visit_ids:
        return [], []
    try:
        rows = hub_client.list_visits(jobber_visit_ids=visit_ids) or []
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in stage1 Hub visit lookup failed: %s", exc)
        return [], []
    return _collect_techs_from_hub_rows(rows)


def _tech_ids_from_hub_client(client_id):
    """When Jobber visit fetch is throttled, use visits already stored from VISIT_COMPLETE."""
    if not client_id:
        return [], []
    try:
        rows = hub_client.list_visits(client_id=client_id) or []
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in stage1 Hub visits by client failed: %s", exc)
        return [], []
    return _collect_techs_from_hub_rows(rows, first_clean_only=True)


def _tech_ids_from_jobber(jobs):
    techs = []
    visit_ids = []
    seen = set()
    for job in jobs or []:
        detail, err = jobber.get_job_visits_with_assignees(job.get("id"))
        if err or not detail:
            logger.warning("Lock-in stage1 job visits %s: %s", job.get("id"), err)
            continue
        for visit in ((detail.get("visits") or {}).get("nodes") or []):
            visit_ids.append(str(visit.get("id")))
            for uid in assigned_user_ids(visit):
                if uid not in seen:
                    seen.add(uid)
                    techs.append(uid)
    return techs, visit_ids


def _expected_first_recurring_start(recurring_jobs):
    """Make used 2nd visit startAt on a related job; else unknown."""
    for job in recurring_jobs or []:
        visits, err = jobber.list_job_visits(job.get("id"))
        if err:
            continue
        visits = sorted(visits or [], key=lambda v: v.get("startAt") or "")
        if len(visits) >= 2:
            return parse_iso(visits[1].get("startAt"))
        if len(visits) == 1:
            return parse_iso(visits[0].get("startAt"))
    return None


def process_quote_approved(quote_id):
    quote_id = str(quote_id or "").strip()
    if not quote_id:
        return {"ok": False, "error": "missing quote id"}

    quote, err = jobber.get_quote(quote_id)
    if err:
        return {"ok": False, "error": err}
    if not quote:
        return {"ok": False, "skipped": True, "reason": "quote_not_found"}

    client = quote.get("client") or {}
    client_id = str(client.get("id") or "")
    client_name = client.get("name") or " ".join(
        p for p in [client.get("firstName"), client.get("lastName")] if p
    ).strip()
    if not client_id:
        return {"ok": False, "skipped": True, "reason": "no_client"}

    jobs, err = jobber.get_client_jobs(client_id)
    if err:
        return {"ok": False, "error": err}

    first_clean_jobs, recurring_jobs = classify_jobs(jobs)
    if not recurring_jobs:
        return {"ok": True, "skipped": True, "reason": "no_recurring_job_title"}

    frequency = pick_frequency(recurring_jobs)
    recurring_job_id = str((recurring_jobs[0] or {}).get("id") or "")

    source_jobs = first_clean_jobs or [
        j for j in jobs if title_is_first_cleaning((j or {}).get("title"))
    ]
    jobber_techs, jobber_visit_ids = _tech_ids_from_jobber(source_jobs or first_clean_jobs)
    hub_techs, hub_visit_ids = _tech_ids_from_hub_visits(jobber_visit_ids)
    if not hub_techs and not jobber_techs:
        hub_techs, hub_visit_ids = _tech_ids_from_hub_client(client_id)
        if hub_techs:
            logger.info(
                "Lock-in stage1 quote=%s: techs from Hub visits by client (Jobber visits throttled or empty)",
                quote_id,
            )
    technician_jobber_ids = hub_techs or jobber_techs
    original_visit_ids = hub_visit_ids or jobber_visit_ids

    if not technician_jobber_ids:
        logger.warning("Lock-in stage1 quote=%s: no technicians from first-clean visits", quote_id)
        return {"ok": True, "skipped": True, "reason": "no_technicians"}

    expected = _expected_first_recurring_start(recurring_jobs)
    confirm_label = format_confirm_date(expected)

    try:
        result = hub_client.create_pending(
            {
                "quote_id": quote_id,
                "client_id": client_id,
                "client_name": client_name,
                "job_id": recurring_job_id,
                "original_visit_ids": original_visit_ids,
                "quote_sent_at": quote.get("createdAt"),
                "quote_approved_at": quote.get("createdAt"),
                "frequency": frequency,
                "expected_first_visit_at": expected.isoformat() if expected else None,
                "technician_jobber_ids": technician_jobber_ids,
            }
        )
    except hub_client.HubLockInError as exc:
        return {"ok": False, "error": str(exc)}

    pending = (result or {}).get("pending") or {}
    created = bool((result or {}).get("created"))
    sms_results = []
    if created:
        for bonus in pending.get("bonuses") or []:
            sms_results.append(_sms_potential(bonus, client_name, frequency, confirm_label))
    return {
        "ok": True,
        "created": created,
        "pending_id": pending.get("id"),
        "sms": sms_results,
        "reason": None if created else "duplicate_or_rule1",
    }


def _sms_potential(bonus, client_name, frequency, confirm_label):
    tech = bonus.get("technician") or {}
    amount = bonus.get("amount") or "0"
    try:
        if float(amount) <= 0:
            logger.warning(
                "Lock-in SMS skipped amount=0 user=%s position=%s",
                tech.get("id"),
                bonus.get("position_snapshot"),
            )
            return {"skipped": True, "reason": "amount_zero", "technician_id": tech.get("id")}
    except (TypeError, ValueError):
        pass

    cid, err = ghl_sms.resolve_staff_contact(
        phone=tech.get("phone") or "",
        name=tech.get("name") or "",
        existing_ghl_id=tech.get("ghl_id") or "",
    )
    if err:
        logger.warning("Lock-in potential SMS contact: %s", err)
        return {"ok": False, "error": err, "technician_id": tech.get("id")}

    if cid and cid != (tech.get("ghl_id") or "") and tech.get("id"):
        try:
            hub_client.set_user_ghl_id(tech["id"], cid)
        except hub_client.HubLockInError as exc:
            logger.warning("Lock-in store ghl_id: %s", exc)

    msg = _potential_sms(
        client_name=client_name,
        amount=amount,
        frequency=frequency,
        confirm_date=confirm_label,
    )
    _, serr = ghl_sms.send_sms(contact_id=cid, to_number=tech.get("phone") or "", message=msg)
    if serr:
        logger.warning("Lock-in potential SMS send: %s", serr)
        return {"ok": False, "error": serr, "technician_id": tech.get("id")}
    try:
        hub_client.mark_bonus_sms(bonus["id"], potential_sms_sent=True)
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in mark potential SMS: %s", exc)
    return {"ok": True, "technician_id": tech.get("id")}
