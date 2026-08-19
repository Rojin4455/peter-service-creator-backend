"""
Jobber VISIT_COMPLETE → set GHL contact custom field Visit Completed? = yes.

SC only flips the trigger field. GHL workflows own Visit Date, Visit Count, SMS, and
clearing Visit Completed? so the next visit can fire again.
"""
import logging

from decouple import config
from django.db import IntegrityError

from jobber_app.client import get_visit_for_ghl_feedback
from jobber_app.ghl_contacts import (
    _get_credentials,
    _location_id,
    find_ghl_contact_for_jobber_client,
    get_contact_by_id,
    update_contact_custom_fields,
)
from jobber_app.lock_in.matching import is_internal_client
from jobber_app.models import (
    GhlContactJobberClientMap,
    JobberClientGhlTagSyncState,
    JobberVisitCompletedGhlTrigger,
)

logger = logging.getLogger(__name__)

DEFAULT_VISIT_COMPLETED_FIELD_ID = "nX55NHpRyzOnQkkvdHOK"
DEFAULT_VISIT_COMPLETED_FIELD_VALUE = "true"


def _field_id():
    return (
        config("GHL_VISIT_COMPLETED_FIELD_ID", default=DEFAULT_VISIT_COMPLETED_FIELD_ID) or ""
    ).strip() or DEFAULT_VISIT_COMPLETED_FIELD_ID


def _field_value():
    return (
        config("GHL_VISIT_COMPLETED_FIELD_VALUE", default=DEFAULT_VISIT_COMPLETED_FIELD_VALUE) or ""
    ).strip() or DEFAULT_VISIT_COMPLETED_FIELD_VALUE


def _resolve_location_id():
    loc = _location_id(_get_credentials())
    if loc:
        return loc, None
    return "", "GHL_LOCATION_ID required"


def _mapped_ghl_contact_id(jobber_client_id):
    cid = str(jobber_client_id or "").strip()
    if not cid:
        return ""
    row = (
        GhlContactJobberClientMap.objects.filter(jobber_client_id=cid)
        .order_by("-updated_at")
        .first()
    )
    if row and (row.ghl_contact_id or "").strip():
        return row.ghl_contact_id.strip()
    st = JobberClientGhlTagSyncState.objects.filter(jobber_client_id=cid).first()
    if st and (st.ghl_contact_id or "").strip():
        return st.ghl_contact_id.strip()
    return ""


def _resolve_ghl_contact(client, location_id):
    """Return (contact_id or None, error or None). None+None means not found."""
    mapped = _mapped_ghl_contact_id((client or {}).get("id"))
    if mapped:
        contact, err = get_contact_by_id(mapped)
        if contact and contact.get("id"):
            return str(contact["id"]), None
        if err:
            logger.warning(
                "VISIT_COMPLETE GHL mapped contact %s unusable: %s",
                mapped,
                err,
            )

    contact, err = find_ghl_contact_for_jobber_client(client or {}, location_id)
    if err:
        return None, err
    if contact and contact.get("id"):
        return str(contact["id"]), None
    return None, None


def process_visit_complete_ghl_feedback(visit_id):
    """
    Set GHL Visit Completed? to yes for the Jobber visit's client.

    Missing GHL contact → ok=True skipped (do not 5xx Jobber).
    Duplicate visit_id → ok=True skipped.
    """
    visit_id = str(visit_id or "").strip()
    if not visit_id:
        return {"ok": False, "error": "missing visit id"}

    if JobberVisitCompletedGhlTrigger.objects.filter(jobber_visit_id=visit_id).exists():
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_processed",
            "jobber_visit_id": visit_id,
        }

    visit, err = get_visit_for_ghl_feedback(visit_id)
    if err:
        return {"ok": False, "error": err, "jobber_visit_id": visit_id}
    if not visit:
        return {"ok": False, "skipped": True, "reason": "visit_not_found", "jobber_visit_id": visit_id}

    client = visit.get("client") or {}
    client_name = client.get("name") or ""
    if is_internal_client(client_name):
        return {
            "ok": True,
            "skipped": True,
            "reason": "internal_client",
            "jobber_visit_id": visit_id,
        }

    try:
        row = JobberVisitCompletedGhlTrigger.objects.create(jobber_visit_id=visit_id)
    except IntegrityError:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_processed",
            "jobber_visit_id": visit_id,
        }

    location_id, loc_err = _resolve_location_id()
    if loc_err:
        row.delete()
        return {"ok": False, "error": loc_err, "jobber_visit_id": visit_id}

    ghl_id, gerr = _resolve_ghl_contact(client, location_id)
    if gerr:
        row.delete()
        logger.warning("VISIT_COMPLETE GHL lookup failed visit=%s: %s", visit_id, gerr)
        return {"ok": False, "error": gerr, "jobber_visit_id": visit_id}

    if not ghl_id:
        row.delete()
        logger.warning(
            "VISIT_COMPLETE GHL contact missing visit=%s client=%s name=%s",
            visit_id,
            client.get("id"),
            client_name,
        )
        return {
            "ok": True,
            "skipped": True,
            "reason": "ghl_contact_not_found",
            "jobber_visit_id": visit_id,
            "jobber_client_id": client.get("id") or "",
        }

    ok, uerr = update_contact_custom_fields(
        ghl_id,
        [{"id": _field_id(), "field_value": _field_value()}],
    )
    if not ok:
        row.delete()
        logger.warning(
            "VISIT_COMPLETE GHL field update failed visit=%s contact=%s: %s",
            visit_id,
            ghl_id,
            uerr,
        )
        return {
            "ok": False,
            "error": uerr,
            "jobber_visit_id": visit_id,
            "ghl_contact_id": ghl_id,
        }

    row.ghl_contact_id = ghl_id
    row.save(update_fields=["ghl_contact_id"])
    logger.warning(
        "VISIT_COMPLETE GHL Visit Completed?=yes visit=%s contact=%s",
        visit_id,
        ghl_id,
    )
    return {
        "ok": True,
        "jobber_visit_id": visit_id,
        "ghl_contact_id": ghl_id,
        "field_id": _field_id(),
    }
