"""
GHL contact → Jobber client sync.

When a contact is created or updated in GoHighLevel, ensure a matching Jobber client
exists (matched by email or phone). Creates the client if not found.
"""
import logging

from .client import create_client, search_clients
from .ghl_contacts import get_contact_by_id, ghl_contact_email_and_phone
from .models import GhlContactJobberClientMap

logger = logging.getLogger(__name__)


def ghl_contact_names(contact):
    """Extract first/last name from a GHL contact dict."""
    if not isinstance(contact, dict):
        return "", ""
    fn = (contact.get("firstName") or contact.get("first_name") or "").strip()
    ln = (contact.get("lastName") or contact.get("last_name") or "").strip()
    if not fn and not ln:
        name = (contact.get("name") or contact.get("contactName") or "").strip()
        if name:
            parts = name.split(None, 1)
            fn = parts[0]
            ln = parts[1] if len(parts) > 1 else ""
    return fn, ln


def sync_ghl_contact_to_jobber(*, ghl_contact_id):
    """
    Ensure a Jobber client exists for the given GHL contact.

    1. Load GHL contact by id.
    2. Search Jobber by email or phone.
    3. If not found, create Jobber client.
    4. Persist ghl_contact_id ↔ jobber_client_id mapping.

    Returns dict: ok, skipped?, reason?, client_created?, ghl_contact_id?, jobber_client_id?, error?
    """
    ghl_contact_id = str(ghl_contact_id or "").strip()
    if not ghl_contact_id:
        return {"ok": False, "error": "contactId required"}

    existing_map = GhlContactJobberClientMap.objects.filter(ghl_contact_id=ghl_contact_id).first()
    if existing_map and existing_map.jobber_client_id:
        return {
            "ok": True,
            "skipped": True,
            "reason": "already_mapped",
            "ghl_contact_id": ghl_contact_id,
            "jobber_client_id": existing_map.jobber_client_id,
            "client_created": existing_map.client_created,
        }

    contact, cerr = get_contact_by_id(ghl_contact_id)
    if cerr or not contact:
        return {
            "ok": False,
            "error": f"get_contact_by_id_failed: {cerr or 'GHL contact not found'}",
            "ghl_contact_id": ghl_contact_id,
        }

    first_name, last_name = ghl_contact_names(contact)
    email, phone = ghl_contact_email_and_phone(contact)

    if not first_name:
        first_name = (email.split("@")[0] if email else "") or "Contact"
    if not last_name:
        last_name = "."

    if not email and not phone:
        return {
            "ok": False,
            "error": "GHL contact has no email or phone — cannot match or create Jobber client",
            "ghl_contact_id": ghl_contact_id,
        }

    search_term = email or phone
    nodes, _, serr = search_clients(search_term, first=5)
    if serr:
        return {
            "ok": False,
            "error": serr,
            "ghl_contact_id": ghl_contact_id,
        }

    client_created = False
    jobber_client_id = None
    if nodes:
        jobber_client_id = nodes[0].get("id")

    if not jobber_client_id:
        client, cerr = create_client(first_name, last_name, email=email, phone=phone)
        if cerr or not client:
            return {
                "ok": False,
                "error": cerr or "Jobber clientCreate returned no client",
                "ghl_contact_id": ghl_contact_id,
            }
        jobber_client_id = client.get("id")
        client_created = True
        logger.info(
            "Created Jobber client for GHL contact=%s jobber_client=%s",
            ghl_contact_id,
            jobber_client_id,
        )
    else:
        logger.info(
            "Jobber client already exists for GHL contact=%s jobber_client=%s",
            ghl_contact_id,
            jobber_client_id,
        )

    if not jobber_client_id:
        return {
            "ok": False,
            "error": "Jobber client id missing after search/create",
            "ghl_contact_id": ghl_contact_id,
        }

    GhlContactJobberClientMap.objects.update_or_create(
        ghl_contact_id=ghl_contact_id,
        defaults={
            "jobber_client_id": str(jobber_client_id),
            "client_created": client_created,
        },
    )

    return {
        "ok": True,
        "ghl_contact_id": ghl_contact_id,
        "jobber_client_id": str(jobber_client_id),
        "client_created": client_created,
        "skipped": not client_created,
        "reason": "client_already_in_jobber" if not client_created else None,
    }
