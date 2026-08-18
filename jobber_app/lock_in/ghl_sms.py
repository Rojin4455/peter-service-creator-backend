"""GHL Conversations SMS for lock-in — PIT only (not Marketplace OAuth)."""

import logging
from urllib.parse import quote

from decouple import config

from jobber_app.ghl_calendar_client import _private_integration_token, _request
from jobber_app.ghl_contacts import normalize_ghl_tags

from .constants import DEFAULT_STAFF_TAG

logger = logging.getLogger(__name__)


def _from_number():
    return (config("GHL_SMS_FROM_NUMBER", default="") or "").strip()


def _staff_tag():
    return (config("GHL_STAFF_TAG", default="") or DEFAULT_STAFF_TAG).strip()


def _location_id():
    return (config("GHL_LOCATION_ID", default="") or "").strip()


def _ensure_pit():
    if not _private_integration_token():
        return (
            "GHL_PRIVATE_INTEGRATION_TOKEN (or GHL_PIT) is required for lock-in SMS. "
            "Marketplace OAuth is not used for this flow."
        )
    return None


def _get_contact_by_id(contact_id):
    data, err = _request("GET", f"/contacts/{contact_id}")
    if err:
        return None, err
    c = data.get("contact") if isinstance(data, dict) else None
    if not isinstance(c, dict):
        return None, "No contact in GHL response"
    return c, None


def _search_contact(location_id, query):
    if not location_id or not query:
        return None, None
    path = f"/contacts/?locationId={quote(location_id, safe='')}&query={quote(str(query), safe='')}"
    data, err = _request("GET", path)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, None
    contacts = data.get("contacts")
    if isinstance(contacts, list) and contacts:
        return contacts[0], None
    c = data.get("contact")
    if isinstance(c, dict):
        return c, None
    return None, None


def create_contact(*, phone, name, location_id, tags=None):
    parts = (name or "").strip().split(None, 1)
    payload = {
        "locationId": location_id,
        "phone": phone,
        "firstName": parts[0] if parts else "Staff",
    }
    if len(parts) > 1:
        payload["lastName"] = parts[1]
    if tags:
        payload["tags"] = list(tags)
    data, err = _request("POST", "/contacts/", json=payload)
    if err:
        return None, err
    contact = (data or {}).get("contact") if isinstance(data, dict) else None
    if not isinstance(contact, dict):
        return None, "No contact in GHL create response"
    return contact, None


def resolve_staff_contact(*, phone, name, existing_ghl_id=""):
    """Find or create GHL contact for a Hub technician. Returns (contact_id, error)."""
    pit_err = _ensure_pit()
    if pit_err:
        return None, pit_err

    location_id = _location_id()
    if not location_id:
        return None, "GHL_LOCATION_ID required"

    contact = None
    if existing_ghl_id:
        contact, err = _get_contact_by_id(existing_ghl_id)
        if err:
            logger.warning("GHL get contact %s failed: %s", existing_ghl_id, err)
            contact = None

    if not contact and phone:
        contact, err = _search_contact(location_id, phone)
        if err:
            return None, err

    tag = _staff_tag()
    if not contact:
        if not phone:
            return None, "Technician has no phone; cannot create GHL contact"
        contact, err = create_contact(
            phone=phone, name=name, location_id=location_id, tags=[tag] if tag else None
        )
        if err:
            return None, err

    cid = str(contact.get("id") or "")
    if not cid:
        return None, "GHL contact missing id"

    if tag:
        current = normalize_ghl_tags(contact)
        if tag not in current:
            _, uerr = _request("PUT", f"/contacts/{cid}", json={"tags": sorted(set(current + [tag]))})
            if uerr:
                logger.warning("GHL tag staff contact %s: %s", cid, uerr)
    return cid, None


def send_sms(*, contact_id, to_number, message):
    pit_err = _ensure_pit()
    if pit_err:
        return None, pit_err
    from_number = _from_number()
    if not from_number:
        return None, "GHL_SMS_FROM_NUMBER is not configured"
    if not contact_id:
        return None, "contactId required"
    if not to_number:
        return None, "toNumber required"
    payload = {
        "type": "SMS",
        "contactId": contact_id,
        "message": message,
        "fromNumber": from_number,
        "toNumber": to_number,
    }
    data, err = _request("POST", "/conversations/messages", json=payload)
    if err:
        return None, err
    return data, None
