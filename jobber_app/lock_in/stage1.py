"""Stage 1 — QUOTE_APPROVED → pending lock-in + potential SMS."""

import logging

from . import ghl_sms, hub_client, jobber
from .matching import (
    assigned_user_ids,
    classify_jobs,
    format_confirm_date,
    frequency_from_quote,
    is_internal_client,
    job_looks_recurring,
    parse_iso,
    pick_frequency,
    recurring_frequency_from_title,
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
    """Techs from Hub visits already stored for this client (VISIT_COMPLETE)."""
    if not client_id:
        return [], []
    try:
        rows = hub_client.list_visits(client_id=client_id) or []
    except hub_client.HubLockInError as exc:
        logger.warning("Lock-in stage1 Hub visits by client failed: %s", exc)
        return [], []
    first = [
        r for r in (rows or []) if title_is_first_cleaning((r or {}).get("title") or "")
    ]
    if first:
        return _collect_techs_from_hub_rows(first)
    prior = [
        r
        for r in (rows or [])
        if not recurring_frequency_from_title((r or {}).get("title") or "")
    ]
    return _collect_techs_from_hub_rows(prior)


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
        raw = jobber.list_job_visits(job.get("id"))
        if not (isinstance(raw, (list, tuple)) and len(raw) == 2):
            continue
        visits, err = raw
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
    if is_internal_client(client_name):
        return {"ok": True, "skipped": True, "reason": "internal_client"}

    jobs, err = jobber.get_client_jobs(client_id)
    if err:
        return {"ok": False, "error": err}

    first_clean_jobs, recurring_jobs = classify_jobs(jobs)
    frequency = pick_frequency(recurring_jobs) or frequency_from_quote(quote)
    if not frequency:
        return {"ok": True, "skipped": True, "reason": "no_recurring_signal"}

    recurring_job_id = ""
    if recurring_jobs:
        recurring_job_id = str((recurring_jobs[0] or {}).get("id") or "")

    hub_techs, hub_visit_ids = _tech_ids_from_hub_client(client_id)
    jobber_techs, jobber_visit_ids = [], []
    if not hub_techs:
        source_jobs = first_clean_jobs or [
            j
            for j in (jobs or [])
            if not recurring_frequency_from_title((j or {}).get("title") or "")
        ]
        jobber_techs, jobber_visit_ids = _tech_ids_from_jobber(source_jobs)
        extra_hub, extra_ids = _tech_ids_from_hub_visits(jobber_visit_ids)
        if extra_hub:
            hub_techs, hub_visit_ids = extra_hub, extra_ids
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
                "quote_approved_at": quote.get("transitionedAt") or quote.get("createdAt"),
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


def _latest_approved_quote_id(client_id):
    quotes, err = jobber.get_client_quotes(client_id)
    if err:
        logger.warning("Lock-in job_create client quotes: %s", err)
        return None
    approved = []
    for q in quotes or []:
        status = str((q or {}).get("quoteStatus") or "").upper()
        if status in ("APPROVED", "CONVERTED"):
            approved.append(q)
    approved.sort(key=lambda q: (q or {}).get("createdAt") or "", reverse=True)
    if not approved:
        return None
    return str((approved[0] or {}).get("id") or "") or None


def _attach_recurring_job(pending_id, job, frequency=None):
    expected = _expected_first_recurring_start([job])
    payload = {"job_id": str(job.get("id") or "")}
    if frequency:
        payload["frequency"] = frequency
    if expected:
        payload["expected_first_visit_at"] = expected.isoformat()
    return hub_client.patch_pending(pending_id, payload)


def process_job_created(job_id):
    """JOB_CREATE — attach recurring job to pending, or retry Stage 1 after convert."""
    job_id = str(job_id or "").strip()
    if not job_id:
        return {"ok": False, "error": "missing job id"}

    job, err = jobber.get_job_lock_in(job_id)
    if err:
        return {"ok": False, "error": err}
    if not job:
        return {"ok": True, "skipped": True, "reason": "job_not_found"}

    client = job.get("client") or {}
    client_id = str(client.get("id") or "")
    client_name = client.get("name") or ""
    if not client_id:
        return {"ok": True, "skipped": True, "reason": "no_client"}
    if is_internal_client(client_name):
        return {"ok": True, "skipped": True, "reason": "internal_client"}
    if title_is_first_cleaning(job.get("title") or ""):
        return {"ok": True, "skipped": True, "reason": "first_cleaning_job"}

    quote_id = str(((job.get("quote") or {}).get("id")) or "")
    looks_recurring = job_looks_recurring(job)
    job_freq = recurring_frequency_from_title(job.get("title") or "")

    if not quote_id and not looks_recurring:
        return {"ok": True, "skipped": True, "reason": "not_recurring_job"}

    try:
        looked = hub_client.lookup_pending(client_id, job_id)
    except hub_client.HubLockInError as exc:
        return {"ok": False, "error": str(exc)}
    pending = (looked or {}).get("pending") or {}
    pending_id = pending.get("id")
    existing_job = str(pending.get("job_id") or "")

    if pending_id and existing_job and existing_job != job_id:
        return {
            "ok": True,
            "skipped": True,
            "reason": "pending_already_linked",
            "pending_id": pending_id,
        }

    if pending_id and (not existing_job or existing_job == job_id):
        try:
            patched = _attach_recurring_job(
                pending_id, job, frequency=job_freq or pending.get("frequency")
            )
        except hub_client.HubLockInError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "attached": True,
            "created": False,
            "pending_id": pending_id,
            "pending": (patched or {}).get("pending") or pending,
        }

    if not quote_id:
        quote_id = _latest_approved_quote_id(client_id) or ""
    if not quote_id:
        return {"ok": True, "skipped": True, "reason": "no_approved_quote"}

    result = process_quote_approved(quote_id)
    pending_id = (result or {}).get("pending_id")
    if pending_id:
        try:
            _attach_recurring_job(pending_id, job, frequency=job_freq or None)
        except hub_client.HubLockInError as exc:
            logger.warning("Lock-in job_create attach after stage1: %s", exc)
        result = {**(result or {}), "job_id": job_id, "attached": True}
    return result


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
