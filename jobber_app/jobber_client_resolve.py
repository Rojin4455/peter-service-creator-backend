"""
Resolve a GHL contact to a Jobber client id (search-only).

Used by note sync, tag sync, and contact sync before optional clientCreate.
"""
import logging
import re

from .client import search_clients
from .models import GhlContactJobberClientMap

logger = logging.getLogger(__name__)


def phone_search_variants(phone):
    """Build distinct Jobber searchTerm candidates from a phone string."""
    if not phone:
        return []
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    variants = []

    def add(value):
        s = str(value or "").strip()
        if s and s not in variants:
            variants.append(s)

    add(raw)
    if digits:
        add(digits)
    if len(digits) == 11 and digits.startswith("1"):
        add(f"+{digits}")
        add(digits[1:])
    elif len(digits) == 10:
        add(f"+1{digits}")
        add(digits)
    return variants


def _search_jobber_client(term, *, first=5):
    nodes, _, err = search_clients(term, first=first)
    if err:
        return None, err
    if not nodes:
        return None, None
    client_id = (nodes[0] or {}).get("id")
    if not client_id:
        return None, "Jobber search returned no id"
    return str(client_id), None


def resolve_jobber_client_for_ghl_contact(ghl_contact_id, email, phone):
    """
    Find Jobber client for a GHL contact using map → email → phone variants.

    Returns dict with ok, jobber_client_id, match_source; or ok=False and error.
    """
    ghl_contact_id = str(ghl_contact_id or "").strip()
    email = (email or "").strip()
    phone = (phone or "").strip()

    if ghl_contact_id:
        mapped = GhlContactJobberClientMap.objects.filter(ghl_contact_id=ghl_contact_id).first()
        if mapped and mapped.jobber_client_id:
            logger.info(
                "Resolved Jobber client via GhlContactJobberClientMap contact=%s client=%s",
                ghl_contact_id,
                mapped.jobber_client_id,
            )
            return {
                "ok": True,
                "jobber_client_id": str(mapped.jobber_client_id),
                "match_source": "ghl_contact_map",
            }

    if email:
        client_id, err = _search_jobber_client(email)
        if err:
            return {"ok": False, "error": err, "ghl_contact_id": ghl_contact_id or None}
        if client_id:
            logger.info(
                "Resolved Jobber client via email search contact=%s client=%s",
                ghl_contact_id,
                client_id,
            )
            return {
                "ok": True,
                "jobber_client_id": client_id,
                "match_source": "email_search",
            }

    for variant in phone_search_variants(phone):
        client_id, err = _search_jobber_client(variant)
        if err:
            return {"ok": False, "error": err, "ghl_contact_id": ghl_contact_id or None}
        if client_id:
            logger.info(
                "Resolved Jobber client via phone search contact=%s term=%s client=%s",
                ghl_contact_id,
                variant,
                client_id,
            )
            return {
                "ok": True,
                "jobber_client_id": client_id,
                "match_source": "phone_search",
            }

    return {
        "ok": False,
        "error": "No Jobber client found for this GHL contact email/phone",
        "ghl_contact_id": ghl_contact_id or None,
    }
