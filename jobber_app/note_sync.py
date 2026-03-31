"""
Forward GHL contact CRM notes → Jobber client notes (internal notes area).

Triggered by inbound webhook (GHL NoteCreate / workflow) with contactId + note id + body.
Idempotent via JobberGhlNoteForward (ghl_note_id unique).
"""
import logging

from .client import append_ghl_note_to_jobber_client, search_clients
from .ghl_contacts import (
    _get_credentials,
    _location_id,
    get_contact_by_id,
    get_note_by_id,
    list_contact_notes,
    search_contact_notes,
    ghl_contact_email_and_phone,
    note_dict_body,
)
from .models import JobberGhlNoteForward

logger = logging.getLogger(__name__)


def _latest_ghl_note_for_contact(ghl_contact_id):
    """Best-effort latest note for a contact via documented contacts notes endpoint."""
    creds = _get_credentials()
    if not creds:
        return None, "GHL not connected"
    location_id = _location_id(creds)
    if not location_id:
        return None, "GHL location id missing"
    notes, err = list_contact_notes(ghl_contact_id, limit=20)
    if err or not notes:
        # Fallback for accounts where /notes/search is available/required.
        notes, err = search_contact_notes(location_id, ghl_contact_id, limit=20, offset=0)
    if err:
        return None, err
    if not notes:
        return None, "No GHL notes found for this contact"

    def _sort_key(n):
        # Prefer created/date-added-ish fields (ISO strings sort lexicographically).
        if not isinstance(n, dict):
            return ""
        return str(
            n.get("dateAdded")
            or n.get("createdAt")
            or n.get("updatedAt")
            or n.get("lastUpdated")
            or ""
        )

    notes_sorted = sorted(notes, key=_sort_key, reverse=True)
    return notes_sorted[0], None


def sync_ghl_note_to_jobber(*, ghl_contact_id, ghl_note_id, note_body=None):
    """
    Append one GHL note onto the matching Jobber client's notes.

    If note_body is None, fetches the note via GET /notes/:id (when id is present).

    Returns dict: ok, skipped, reason?, error?, ghl_contact_id?, ghl_note_id?, jobber_client_id?, written?
    """
    ghl_contact_id = str(ghl_contact_id or "").strip()
    ghl_note_id = str(ghl_note_id or "").strip()

    if not ghl_contact_id:
        return {"ok": False, "error": "contactId required"}
    latest_note = None
    if not ghl_note_id:
        latest_note, lerr = _latest_ghl_note_for_contact(ghl_contact_id)
        if lerr or not latest_note:
            return {"ok": False, "error": lerr or "Could not resolve latest note", "ghl_contact_id": ghl_contact_id}
        ghl_note_id = str(
            latest_note.get("id")
            or latest_note.get("noteId")
            or latest_note.get("note_id")
            or ""
        ).strip()
        if not ghl_note_id:
            return {"ok": False, "error": "Latest GHL note has no id", "ghl_contact_id": ghl_contact_id}

    if JobberGhlNoteForward.objects.filter(ghl_note_id=ghl_note_id).exists():
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_synced",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    body = (note_body or "").strip() if note_body is not None else ""
    if not body:
        if latest_note:
            body = note_dict_body(latest_note)
        if not body:
            note_obj, nerr = get_note_by_id(ghl_note_id)
            if nerr or not note_obj:
                return {
                    "ok": False,
                    "error": nerr or "Could not load GHL note",
                    "ghl_contact_id": ghl_contact_id,
                    "ghl_note_id": ghl_note_id,
                }
            body = note_dict_body(note_obj)
    if not body:
        return {
            "ok": False,
            "error": "GHL note has empty body",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    contact, cerr = get_contact_by_id(ghl_contact_id)
    if cerr or not contact:
        return {
            "ok": False,
            "error": cerr or "GHL contact not found",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    email, phone = ghl_contact_email_and_phone(contact)
    if not email and not phone:
        return {
            "ok": False,
            "error": "GHL contact has no email or phone to match Jobber client",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    search_term = email or phone
    nodes, _, serr = search_clients(search_term, first=5)
    if serr:
        return {
            "ok": False,
            "error": serr,
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }
    if not nodes:
        return {
            "ok": False,
            "error": "No Jobber client found for this GHL contact email/phone",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    jobber_client_id = nodes[0].get("id")
    if not jobber_client_id:
        return {
            "ok": False,
            "error": "Jobber search returned no id",
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
        }

    ok, uerr, did_write = append_ghl_note_to_jobber_client(
        str(jobber_client_id),
        ghl_note_id,
        body,
    )
    if not ok:
        return {
            "ok": False,
            "error": uerr,
            "ghl_contact_id": ghl_contact_id,
            "ghl_note_id": ghl_note_id,
            "jobber_client_id": str(jobber_client_id),
        }

    JobberGhlNoteForward.objects.update_or_create(
        ghl_note_id=ghl_note_id,
        defaults={
            "ghl_contact_id": ghl_contact_id,
            "jobber_client_id": str(jobber_client_id),
        },
    )
    logger.info(
        "Forwarded GHL note to Jobber contact=%s note=%s client=%s written=%s",
        ghl_contact_id,
        ghl_note_id,
        jobber_client_id,
        did_write,
    )
    return {
        "ok": True,
        "ghl_contact_id": ghl_contact_id,
        "ghl_note_id": ghl_note_id,
        "jobber_client_id": str(jobber_client_id),
        "written": did_write,
        "skipped_body_duplicate": not did_write,
    }
