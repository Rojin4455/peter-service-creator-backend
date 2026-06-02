"""
GHL contact → Jobber client sync.

When a contact is created or updated in GoHighLevel, ensure a matching Jobber client
exists (matched by email or phone). Creates the client if not found.
When GHL has a full service address, ensure a Jobber property exists on that client.
"""
import logging

from .client import (
    create_client,
    create_property_for_client,
    get_client_properties,
    search_clients,
)
from .ghl_contacts import (
    get_contact_by_id,
    ghl_contact_email_and_phone,
    ghl_contact_service_address,
)
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


def _ensure_jobber_property(jobber_client_id, address):
    """
    Create a Jobber property when the client has none and GHL has a full address.
    Returns dict: property_id?, property_created?, property_skipped?, property_error?
    """
    out = {
        "property_id": None,
        "property_created": False,
        "property_skipped": False,
        "property_skip_reason": None,
        "property_error": None,
    }
    if not jobber_client_id:
        out["property_skipped"] = True
        out["property_skip_reason"] = "no_jobber_client_id"
        return out
    if not address:
        out["property_skipped"] = True
        out["property_skip_reason"] = "incomplete_ghl_address"
        return out

    prop_id, _, perr = get_client_properties(jobber_client_id)
    if perr:
        out["property_error"] = perr
        return out
    if prop_id:
        out["property_id"] = str(prop_id)
        out["property_skipped"] = True
        out["property_skip_reason"] = "client_already_has_property"
        return out

    prop, perr = create_property_for_client(
        client_id=jobber_client_id,
        street1=address["street1"],
        city=address["city"],
        province=address["province"],
        postal_code=address["postal_code"],
        street2=address.get("street2"),
    )
    if perr or not prop:
        out["property_error"] = perr or "propertyCreate returned no property"
        return out

    out["property_id"] = str(prop.get("id") or "")
    out["property_created"] = True
    logger.info(
        "Created Jobber property for client=%s property=%s",
        jobber_client_id,
        out["property_id"],
    )
    return out


def _resolve_or_create_jobber_client(contact, *, ghl_contact_id, existing_map=None):
    """
    Find or create Jobber client from GHL contact fields.
    Returns (jobber_client_id, client_created, error_dict or None).
    """
    if existing_map and existing_map.jobber_client_id:
        return str(existing_map.jobber_client_id), False, None

    first_name, last_name = ghl_contact_names(contact)
    email, phone = ghl_contact_email_and_phone(contact)

    if not first_name:
        first_name = (email.split("@")[0] if email else "") or "Contact"
    if not last_name:
        last_name = "."

    if not email and not phone:
        return None, False, {
            "ok": False,
            "error": "GHL contact has no email or phone — cannot match or create Jobber client",
            "ghl_contact_id": ghl_contact_id,
        }

    search_term = email or phone
    nodes, _, serr = search_clients(search_term, first=5)
    if serr:
        return None, False, {"ok": False, "error": serr, "ghl_contact_id": ghl_contact_id}

    client_created = False
    jobber_client_id = nodes[0].get("id") if nodes else None

    if not jobber_client_id:
        client, cerr = create_client(first_name, last_name, email=email, phone=phone)
        if cerr or not client:
            return None, False, {
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
        return None, False, {
            "ok": False,
            "error": "Jobber client id missing after search/create",
            "ghl_contact_id": ghl_contact_id,
        }

    return str(jobber_client_id), client_created, None


def sync_ghl_contact_to_jobber(*, ghl_contact_id):
    """
    Ensure a Jobber client exists for the given GHL contact and, when GHL has a full
    address, ensure the client has at least one Jobber property (service address).

    Re-runs property creation on later webhooks when address appears (Contact Changed).

    Returns dict: ok, skipped?, reason?, client_created?, property_* fields, etc.
    """
    ghl_contact_id = str(ghl_contact_id or "").strip()
    if not ghl_contact_id:
        return {"ok": False, "error": "contactId required"}

    existing_map = GhlContactJobberClientMap.objects.filter(ghl_contact_id=ghl_contact_id).first()
    client_already_mapped = bool(existing_map and existing_map.jobber_client_id)

    contact, cerr = get_contact_by_id(ghl_contact_id)
    if cerr or not contact:
        return {
            "ok": False,
            "error": f"get_contact_by_id_failed: {cerr or 'GHL contact not found'}",
            "ghl_contact_id": ghl_contact_id,
        }

    jobber_client_id, client_created, err = _resolve_or_create_jobber_client(
        contact,
        ghl_contact_id=ghl_contact_id,
        existing_map=existing_map,
    )
    if err:
        return err

    address = ghl_contact_service_address(contact)
    property_result = _ensure_jobber_property(jobber_client_id, address)

    map_client_created = client_created
    if not map_client_created and existing_map:
        map_client_created = existing_map.client_created
    GhlContactJobberClientMap.objects.update_or_create(
        ghl_contact_id=ghl_contact_id,
        defaults={
            "jobber_client_id": str(jobber_client_id),
            "client_created": map_client_created,
        },
    )

    ok = not property_result.get("property_error")
    result = {
        "ok": ok,
        "ghl_contact_id": ghl_contact_id,
        "jobber_client_id": str(jobber_client_id),
        "client_created": client_created,
        "client_skipped": client_already_mapped,
        "client_skip_reason": "already_mapped" if client_already_mapped else None,
        **property_result,
    }
    if not ok:
        result["error"] = property_result.get("property_error")
    elif client_already_mapped and not client_created and property_result.get("property_skipped"):
        result["skipped"] = True
        result["reason"] = property_result.get("property_skip_reason") or "already_mapped"
    elif not client_created and not property_result.get("property_created"):
        result["skipped"] = True
        result["reason"] = (
            property_result.get("property_skip_reason") or "client_already_in_jobber"
        )
    return result
