"""
GoHighLevel (LeadConnector) Contacts API helpers for tag sync.

Docs: https://marketplace.gohighlevel.com/docs/ghl/contacts/contacts-api
Uses same auth pattern as ghl_calendar_client / quote_app.helpers.
"""
import logging
from urllib.parse import quote

import requests
from decouple import config

from accounts.models import GHLAuthCredentials

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
GHL_API_VERSION = config("GHL_API_VERSION", default="2021-07-28")


def _get_credentials():
    return GHLAuthCredentials.objects.order_by("-updated_at").first()


def _refresh_access_token(creds):
    try:
        client_id = config("GHL_CLIENT_ID")
        client_secret = config("GHL_CLIENT_SECRET")
    except Exception as e:
        return None, f"GHL env not configured: {e}"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(
        f"{GHL_BASE_URL}/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    try:
        body = resp.json()
    except requests.exceptions.JSONDecodeError:
        return None, f"Invalid JSON from GHL token endpoint: {resp.text[:300]}"
    if resp.status_code != 200:
        return None, body.get("error_description") or body.get("error") or resp.text[:300]
    access = body.get("access_token")
    refresh = body.get("refresh_token") or creds.refresh_token
    if not access:
        return None, "Missing access_token in GHL refresh response"
    creds.access_token = access
    creds.refresh_token = refresh
    if body.get("expires_in") is not None:
        creds.expires_in = int(body["expires_in"])
    creds.save(update_fields=["access_token", "refresh_token", "expires_in", "updated_at"])
    return access, None


def _headers(creds, *, include_json=True):
    h = {
        "Accept": "application/json",
        "Authorization": f"Bearer {creds.access_token}",
        "Version": GHL_API_VERSION,
    }
    if include_json:
        h["Content-Type"] = "application/json"
    return h


def _request(method, path, *, json=None, _retry=True):
    creds = _get_credentials()
    if not creds:
        return None, "GHL not connected (GHLAuthCredentials missing)."
    url = f"{GHL_BASE_URL}{path}"
    include_json = method.upper() in ("POST", "PUT", "PATCH")
    resp = requests.request(
        method,
        url,
        headers=_headers(creds, include_json=include_json),
        json=json if include_json else None,
        timeout=45,
    )
    if resp.status_code == 401 and _retry:
        _, err = _refresh_access_token(creds)
        if err:
            return None, f"GHL unauthorized and token refresh failed: {err}"
        creds.refresh_from_db()
        return _request(method, path, json=json, _retry=False)
    try:
        data = resp.json() if resp.content else {}
    except requests.exceptions.JSONDecodeError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        msg = data.get("message") or data.get("error") or data.get("msg") or str(data)[:500]
        return None, f"GHL API {resp.status_code}: {msg}"
    return data, None


def _location_id(creds):
    return (config("GHL_LOCATION_ID", default=None) or "").strip() or (creds.location_id or "").strip()


def get_contact_by_id(contact_id):
    """GET /contacts/:id → (contact dict or None, error)."""
    data, err = _request("GET", f"/contacts/{contact_id}")
    if err:
        return None, err
    c = data.get("contact") if isinstance(data, dict) else None
    if not isinstance(c, dict):
        return None, "No contact in GHL response"
    return c, None


def search_contacts_by_query(location_id, query):
    """GET /contacts/?locationId=&query= → first contact or None."""
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


def find_ghl_contact_for_jobber_client(client_dict, location_id):
    """
    Resolve GHL contact from Jobber client emails/phones.
    Returns (contact dict or None, error or None).
    """
    emails = (client_dict.get("emails") or []) if isinstance(client_dict, dict) else []
    phones = (client_dict.get("phones") or []) if isinstance(client_dict, dict) else []
    primary_email = None
    for e in emails:
        if isinstance(e, dict) and e.get("address"):
            primary_email = (e.get("address") or "").strip()
            if primary_email:
                break
    primary_phone = None
    for p in phones:
        if isinstance(p, dict) and p.get("number"):
            primary_phone = (p.get("number") or "").strip()
            if primary_phone:
                break
    if primary_email:
        c, err = search_contacts_by_query(location_id, primary_email)
        if err:
            return None, err
        if c:
            return c, None
    if primary_phone:
        c, err = search_contacts_by_query(location_id, primary_phone)
        if err:
            return None, err
        if c:
            return c, None
    return None, None


def ghl_contact_email_and_phone(contact):
    """
    Primary email/phone from a LeadConnector contact dict (handles common alternate fields).
    """
    if not isinstance(contact, dict):
        return "", ""
    email = (contact.get("email") or "").strip()
    if not email:
        email = (contact.get("emailLowerCase") or "").strip()
    if not email:
        add = contact.get("additionalEmails") or []
        if isinstance(add, list):
            for item in add:
                if isinstance(item, str) and item.strip():
                    email = item.strip()
                    break
                if isinstance(item, dict):
                    e = (item.get("email") or item.get("value") or "").strip()
                    if e:
                        email = e
                        break
    phone = (contact.get("phone") or contact.get("phoneNumber") or "").strip()
    if not phone:
        alt = contact.get("additionalPhones") or []
        if isinstance(alt, list):
            for item in alt:
                if isinstance(item, str) and item.strip():
                    phone = item.strip()
                    break
                if isinstance(item, dict):
                    p = (item.get("phone") or item.get("phoneNumber") or item.get("value") or "").strip()
                    if p:
                        phone = p
                        break
    return email, phone


def normalize_ghl_tags(contact):
    """Return list of tag strings from a GHL contact dict."""
    if not isinstance(contact, dict):
        return []
    tags = contact.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        return []
    out = []
    for t in tags:
        if isinstance(t, str) and t.strip():
            out.append(t.strip())
        elif isinstance(t, dict):
            s = str(t.get("name") or t.get("label") or t.get("tag") or "").strip()
            if s:
                out.append(s)
    return sorted(set(out))


def update_contact_tags(contact_id, tags_list):
    """
    PUT /contacts/:id with body { tags: [...] }.
    tags_list: list of strings.
    """
    payload = {"tags": list(tags_list)}
    data, err = _request("PUT", f"/contacts/{contact_id}", json=payload)
    if err:
        return False, err
    return True, None


# -----------------------------------------------------------------------------
# CRM Notes
# Prefer documented contacts routes (/contacts/:id/notes),
# keep /notes/search as fallback for older/workflow-style behavior.
# -----------------------------------------------------------------------------


def _notes_list_from_response(data):
    """Normalize various response shapes to a list of note dicts."""
    if not isinstance(data, dict):
        return []
    for key in ("notes", "data", "items", "results"):
        v = data.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict) and isinstance(v.get("notes"), list):
            return v["notes"]
    return []


def search_contact_notes(location_id, contact_id, *, limit=50, offset=0):
    """
    POST /notes/search — list notes for a contact (same API the GHL UI uses).
    Returns (list of note dicts, error or None).
    """
    if not location_id or not contact_id:
        return [], "location_id and contact_id required"
    payload = {
        "locationId": str(location_id).strip(),
        "contactId": str(contact_id).strip(),
        "limit": int(limit),
        "offset": int(offset),
    }
    data, err = _request("POST", "/notes/search", json=payload)
    if err:
        return [], err
    return _notes_list_from_response(data), None


def list_contact_notes(contact_id, *, limit=100):
    """
    GET /contacts/:contactId/notes (documented under contacts.readonly scope).
    Returns (list of note dicts, error or None).
    """
    if not contact_id:
        return [], "contact_id required"
    data, err = _request("GET", f"/contacts/{contact_id}/notes")
    if err:
        return [], err
    notes = _notes_list_from_response(data)
    if limit and isinstance(notes, list):
        notes = notes[: int(limit)]
    return notes, None


def get_note_by_id(note_id, contact_id=None):
    """
    GET note detail (contact-scoped).
    Uses documented route:
      GET /contacts/:contactId/notes/:id
    Falls back to /notes/:id only when contact_id is not provided.
    """
    if not note_id:
        return None, "note_id required"

    if contact_id:
        data, err = _request("GET", f"/contacts/{contact_id}/notes/{note_id}")
        if err:
            return None, err
        if isinstance(data, dict) and isinstance(data.get("note"), dict):
            return data["note"], None
        if isinstance(data, dict) and data.get("id"):
            return data, None
        return None, "Unexpected GHL contact-note response shape"

    data, err = _request("GET", f"/notes/{note_id}")
    if err:
        return None, err
    if isinstance(data, dict) and isinstance(data.get("note"), dict):
        return data["note"], None
    if isinstance(data, dict) and data.get("id"):
        return data, None
    return None, "Unexpected GHL note response shape"


def note_dict_body(note):
    """Extract human-readable body from a GHL note object."""
    if not isinstance(note, dict):
        return ""
    return str(note.get("body") or note.get("note") or note.get("message") or "").strip()
