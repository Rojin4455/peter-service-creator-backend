"""
Bidirectional tag sync: Jobber client tags ↔ GHL contact tags.

- Jobber CLIENT_CREATE / CLIENT_UPDATE webhooks → push tags to GHL (merge with preserved GHL-only tags).
- GHL inbound webhook → push tags to Jobber (merge with preserved Jobber-only tags).

Loop reduction: JobberClientGhlTagSyncState stores last sync source + separate signatures for
Jobber vs GHL tag sets so echo webhooks can be skipped.
"""
import hashlib
import logging

from decouple import config

from quote_app.helpers import BID_IN_PERSON_TAG, QUOTE_STATUS_TAGS

from .client import get_client_for_tag_sync, list_client_tag_names, search_clients, set_client_tags_by_names
from .ghl_contacts import (
    _get_credentials,
    _location_id,
    find_ghl_contact_for_jobber_client,
    get_contact_by_id,
    normalize_ghl_tags,
    update_contact_tags,
)
from .models import JobberClientGhlTagSyncState

logger = logging.getLogger(__name__)


def _signature(tag_list):
    """Stable hash for comparing tag sets (case-insensitive)."""
    normalized = sorted({str(t).strip().lower() for t in (tag_list or []) if str(t).strip()})
    blob = "|".join(normalized).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _parse_preserve_env(key, default_csv):
    raw = config(key, default=default_csv)
    out = set()
    for part in str(raw).split(","):
        s = part.strip().lower()
        if s:
            out.add(s)
    return out


def _ghl_preserve_tags():
    """Tags on GHL we keep when merging Jobber → GHL (quote workflow, etc.)."""
    base = {t.lower() for t in QUOTE_STATUS_TAGS}
    base.add(BID_IN_PERSON_TAG.lower())
    base |= _parse_preserve_env("JOBBER_GHL_TAG_SYNC_PRESERVE_GHL", "")
    return base


def _jobber_preserve_tags():
    """Tags on Jobber we keep when merging GHL → Jobber."""
    return _parse_preserve_env("JOBBER_GHL_TAG_SYNC_PRESERVE_JOBBER", "")


def _get_state(jobber_client_id):
    return JobberClientGhlTagSyncState.objects.filter(jobber_client_id=str(jobber_client_id)).first()


def _save_state_jobber_to_ghl(jobber_client_id, ghl_contact_id, jobber_tag_names, merged_ghl_tags):
    JobberClientGhlTagSyncState.objects.update_or_create(
        jobber_client_id=str(jobber_client_id),
        defaults={
            "ghl_contact_id": str(ghl_contact_id or ""),
            "last_jobber_tag_signature": _signature(jobber_tag_names),
            "last_ghl_tag_signature": _signature(merged_ghl_tags),
            "last_sync_source": "jobber",
        },
    )


def _save_state_ghl_to_jobber(jobber_client_id, ghl_contact_id, ghl_tag_names, jobber_tag_names_after):
    JobberClientGhlTagSyncState.objects.update_or_create(
        jobber_client_id=str(jobber_client_id),
        defaults={
            "ghl_contact_id": str(ghl_contact_id or ""),
            "last_jobber_tag_signature": _signature(jobber_tag_names_after),
            "last_ghl_tag_signature": _signature(ghl_tag_names),
            "last_sync_source": "ghl",
        },
    )


def sync_jobber_client_tags_to_ghl(jobber_client_id):
    """
    Read Jobber client tags and mirror onto matching GHL contact (by email/phone).
    Preserves GHL tags listed in JOBBER_GHL_TAG_SYNC_PRESERVE_GHL + quote status tags.

    Returns dict: { ok, skipped, reason?, jobber_client_id, ghl_contact_id?, error?, tags? }
    """
    creds = _get_credentials()
    if not creds:
        return {"ok": False, "error": "GHL not connected", "jobber_client_id": jobber_client_id}

    location_id = _location_id(creds)
    if not location_id:
        return {"ok": False, "error": "GHL_LOCATION_ID or credentials.location_id required", "jobber_client_id": jobber_client_id}

    client, err = get_client_for_tag_sync(jobber_client_id)
    if err:
        return {"ok": False, "error": err, "jobber_client_id": jobber_client_id}
    if not client:
        return {"ok": False, "error": "Client not found", "jobber_client_id": jobber_client_id}

    jb_names, e2 = list_client_tag_names(jobber_client_id)
    if e2:
        return {"ok": False, "error": e2, "jobber_client_id": jobber_client_id}

    jb_sig = _signature(jb_names)
    st = _get_state(jobber_client_id)
    if st and st.last_sync_source == "ghl" and st.last_jobber_tag_signature == jb_sig:
        return {"ok": True, "skipped": True, "reason": "echo_from_ghl_sync", "jobber_client_id": jobber_client_id}

    ghl_contact, ferr = find_ghl_contact_for_jobber_client(client, location_id)
    if ferr:
        return {"ok": False, "error": ferr, "jobber_client_id": jobber_client_id}
    if not ghl_contact:
        return {"ok": False, "error": "No GHL contact found for this Jobber client email/phone", "jobber_client_id": jobber_client_id}

    ghl_id = ghl_contact.get("id")
    existing_ghl = normalize_ghl_tags(ghl_contact)
    preserve = _ghl_preserve_tags()
    kept = [t for t in existing_ghl if t.lower() in preserve]
    merged = sorted(set(kept) | set(jb_names))
    ok, uerr = update_contact_tags(ghl_id, merged)
    if not ok:
        return {"ok": False, "error": uerr, "jobber_client_id": jobber_client_id, "ghl_contact_id": ghl_id}

    _save_state_jobber_to_ghl(jobber_client_id, ghl_id, jb_names, merged)
    logger.info("Synced Jobber→GHL tags client=%s contact=%s count=%s", jobber_client_id, ghl_id, len(merged))
    return {
        "ok": True,
        "jobber_client_id": jobber_client_id,
        "ghl_contact_id": ghl_id,
        "tags": merged,
    }


def sync_ghl_contact_tags_to_jobber(ghl_contact_id, tag_names_from_payload=None):
    """
    Read GHL contact tags (or use payload), resolve Jobber client by email/phone, update Jobber tags.
    Drops GHL-only preserved tags (quote workflow) from the set applied to Jobber.
    Preserves Jobber tags in JOBBER_GHL_TAG_SYNC_PRESERVE_JOBBER.

    Returns dict: ok, skipped, reason?, jobber_client_id?, ghl_contact_id?, error?, tags?
    """
    creds = _get_credentials()
    if not creds:
        return {"ok": False, "error": "GHL not connected", "ghl_contact_id": ghl_contact_id}

    contact, err = get_contact_by_id(ghl_contact_id)
    if err:
        return {"ok": False, "error": err, "ghl_contact_id": ghl_contact_id}

    if tag_names_from_payload is not None:
        ghl_tags = sorted({str(t).strip() for t in tag_names_from_payload if str(t).strip()})
    else:
        ghl_tags = normalize_ghl_tags(contact)

    ghl_sig = _signature(ghl_tags)

    email = (contact.get("email") or "").strip()
    phone = (contact.get("phone") or contact.get("phoneNumber") or "").strip()
    if not email and not phone:
        return {"ok": False, "error": "GHL contact has no email or phone to match Jobber client", "ghl_contact_id": ghl_contact_id}

    search_term = email or phone
    nodes, _, serr = search_clients(search_term, first=5)
    if serr:
        return {"ok": False, "error": serr, "ghl_contact_id": ghl_contact_id}
    if not nodes:
        return {"ok": False, "error": "No Jobber client found for this GHL contact email/phone", "ghl_contact_id": ghl_contact_id}

    jobber_client_id = nodes[0].get("id")
    if not jobber_client_id:
        return {"ok": False, "error": "Jobber search returned no id", "ghl_contact_id": ghl_contact_id}

    st = _get_state(jobber_client_id)
    if st and st.last_sync_source == "jobber" and st.last_ghl_tag_signature == ghl_sig:
        return {"ok": True, "skipped": True, "reason": "echo_from_jobber_sync", "jobber_client_id": jobber_client_id, "ghl_contact_id": ghl_contact_id}

    jb_existing, je = list_client_tag_names(jobber_client_id)
    if je:
        return {"ok": False, "error": je, "jobber_client_id": jobber_client_id}

    preserve_j = _jobber_preserve_tags()
    kept_j = [t for t in jb_existing if t.lower() in preserve_j]
    preserve_ghl = _ghl_preserve_tags()
    ghl_for_jobber = [t for t in ghl_tags if t.lower() not in preserve_ghl]
    merged_j = sorted(set(kept_j) | set(ghl_for_jobber))

    ok, uerr = set_client_tags_by_names(jobber_client_id, merged_j)
    if not ok:
        return {"ok": False, "error": uerr, "jobber_client_id": jobber_client_id, "ghl_contact_id": ghl_contact_id}

    jb_after, je2 = list_client_tag_names(jobber_client_id)
    if je2:
        jb_after = merged_j

    _save_state_ghl_to_jobber(jobber_client_id, ghl_contact_id, ghl_tags, jb_after)
    logger.info("Synced GHL→Jobber tags client=%s contact=%s count=%s", jobber_client_id, ghl_contact_id, len(merged_j))
    return {
        "ok": True,
        "jobber_client_id": jobber_client_id,
        "ghl_contact_id": ghl_contact_id,
        "tags": merged_j,
    }
