"""
Jobber GraphQL API client.
Uses stored JobberAuthCredentials from accounts app.
Automatically refreshes the access token when it expires.
"""
import json
import logging
import requests
from decouple import config

logger = logging.getLogger(__name__)

JOBBER_GRAPHQL_URL = "https://api.getjobber.com/api/graphql"
JOBBER_TOKEN_URL = "https://api.getjobber.com/api/oauth/token"


def get_access_token():
    """Get current Jobber access token from DB."""
    from accounts.models import JobberAuthCredentials
    creds = JobberAuthCredentials.objects.first()
    if not creds:
        return None
    return creds.access_token


def _refresh_jobber_tokens():
    """
    Exchange refresh_token for new access_token (and possibly new refresh_token).
    Updates JobberAuthCredentials in DB. Returns (new_access_token, None) or (None, error_message).
    """
    from accounts.models import JobberAuthCredentials
    creds = JobberAuthCredentials.objects.first()
    if not creds or not creds.refresh_token:
        return None, "No refresh token. Reconnect Jobber at /api/accounts/jobber/connect/"
    try:
        client_id = config("JOBBER_CLIENT_ID")
        client_secret = config("JOBBER_CLIENT_SECRET")
    except Exception as e:
        return None, f"Jobber env not configured: {e}"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(JOBBER_TOKEN_URL, data=data, timeout=30)
    try:
        response_data = resp.json()
    except requests.exceptions.JSONDecodeError:
        response_data = {}
    if resp.status_code != 200:
        err = (
            response_data.get("error_description")
            or response_data.get("error")
            or resp.text[:300].strip()
        ) or "Unknown error"
        logger.warning("Jobber token refresh failed: %s", err)
        msg = f"Token refresh failed: {err}"
        if "refresh token" in err.lower() and ("not valid" in err.lower() or "invalid" in err.lower() or "expired" in err.lower()):
            msg += " Reconnect Jobber at /api/accounts/jobber/connect/"
        return None, msg
    access_token = response_data.get("access_token")
    refresh_token = response_data.get("refresh_token") or creds.refresh_token
    if not access_token:
        return None, "Missing access_token in refresh response"
    creds.access_token = access_token
    creds.refresh_token = refresh_token
    creds.save(update_fields=["access_token", "refresh_token", "updated_at"])
    logger.info("Jobber access token refreshed successfully")
    return access_token, None


def _is_token_expired_error(status_code, data):
    """Return True if the response indicates an expired or invalid token."""
    if status_code == 401:
        return True
    if status_code == 200 and data:
        errors = data.get("errors") or []
        for e in errors:
            msg = (e.get("message") or "").lower()
            if "token" in msg or "expired" in msg or "unauthorized" in msg or "authenticate" in msg:
                return True
    return False


def _request(query, variables=None, _retried=False):
    """POST a GraphQL request to Jobber. Returns (data dict, error message or None). Auto-refreshes token on expiry."""
    token = get_access_token()
    if not token:
        return None, "Jobber not connected. Complete OAuth at /api/accounts/jobber/connect/"
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-JOBBER-GRAPHQL-VERSION": "2025-04-16",
    }
    resp = requests.post(JOBBER_GRAPHQL_URL, json=payload, headers=headers, timeout=30)
    try:
        data = resp.json() if resp.content else {}
    except requests.exceptions.JSONDecodeError:
        data = {}
    if _is_token_expired_error(resp.status_code, data) and not _retried:
        new_token, err = _refresh_jobber_tokens()
        if err:
            return None, err
        return _request(query, variables, _retried=True)
    if resp.status_code != 200:
        return None, f"Jobber API HTTP {resp.status_code}: {resp.text[:500]}"
    if "errors" in data and data["errors"]:
        err_msg = "; ".join(e.get("message", str(e)) for e in data["errors"])
        return None, err_msg
    return data.get("data"), None


# -----------------------------------------------------------------------------
# Search clients by email or phone (searchTerm)
# -----------------------------------------------------------------------------

QUERY_CLIENTS_SEARCH = """
query SearchForClient($searchTerm: String!, $first: Int) {
  clients(searchTerm: $searchTerm, first: $first) {
    totalCount
    nodes {
      id
      firstName
      lastName
      phones { number }
      emails { address }
    }
  }
}
"""


def search_clients(search_term, first=5):
    """
    Search Jobber clients by email or phone.
    Returns (nodes list, total_count, error_message).
    """
    data, err = _request(QUERY_CLIENTS_SEARCH, {"searchTerm": search_term, "first": first})
    if err:
        return [], 0, err
    clients = data.get("clients") or {}
    nodes = clients.get("nodes") or []
    total = clients.get("totalCount") or 0
    return nodes, total, None


# -----------------------------------------------------------------------------
# Create client
# -----------------------------------------------------------------------------

MUTATION_CLIENT_CREATE = """
mutation CreateClient($input: ClientCreateInput!) {
  clientCreate(input: $input) {
    client {
      id
      firstName
      lastName
      emails { address }
      phones { number }
    }
    userErrors {
      message
      path
    }
  }
}
"""


def create_client(first_name, last_name, email=None, phone=None):
    """
    Create a Jobber client. email and/or phone recommended.
    Returns (client dict or None, error_message).
    """
    input_obj = {
        "firstName": first_name or "",
        "lastName": last_name or "",
    }
    if email:
        input_obj["emails"] = [{"address": email, "primary": True, "description": "MAIN"}]
    else:
        input_obj["emails"] = []
    if phone:
        input_obj["phones"] = [
            {
                "number": str(phone),
                "primary": True,
                "description": "MAIN",
                "smsAllowed": True,
            }
        ]
    else:
        input_obj["phones"] = []

    data, err = _request(MUTATION_CLIENT_CREATE, {"input": input_obj})
    if err:
        return None, err
    result = data.get("clientCreate") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        msg = "; ".join([e.get("message", str(e)) for e in user_errors])
        return None, msg
    client = result.get("client")
    return client, None


# -----------------------------------------------------------------------------
# Visits (calendar / busy slots) for a date range
# -----------------------------------------------------------------------------

QUERY_VISITS_TEMPLATE = """
query CheckCalendarAvailability {{
  visits(filter: {{
    startAt: {{
      after: "{after}",
      before: "{before}"
    }}
  }}) {{
    nodes {{
      id
      title
      startAt
      endAt
    }}
  }}
}}
"""


def get_visits(after_iso, before_iso):
    """
    Get Jobber visits (existing bookings) in a date range.
    after_iso / before_iso: ISO 8601 datetime strings (e.g. "2026-04-15T00:00:00Z").
    Returns (list of visit dicts, error_message).
    """
    query = QUERY_VISITS_TEMPLATE.format(after=after_iso, before=before_iso)
    data, err = _request(query)
    if err:
        return [], err
    visits = data.get("visits") or {}
    nodes = visits.get("nodes") or []
    return nodes, None


QUERY_JOB_VISITS = """
query JobVisits($id: EncodedId!) {
  job(id: $id) {
    id
    visits(first: 100) {
      nodes {
        id
        title
        startAt
        endAt
      }
    }
  }
}
"""


def get_job_visits(job_id):
    """
    Get all visits for a given Jobber job.
    Returns (list of visit dicts, error_message).
    """
    data, err = _request(QUERY_JOB_VISITS, {"id": job_id})
    if err:
        return [], err
    job = (data or {}).get("job") or {}
    visits = (job.get("visits") or {}).get("nodes") or []
    return visits, None


QUERY_VISIT_BY_ID = """
query VisitById($id: EncodedId!) {
  visit(id: $id) {
    id
    title
    startAt
    endAt
  }
}
"""


def get_visit_by_id(visit_id):
    """
    Get one visit by id.
    Returns (visit dict or None, error_message).
    """
    data, err = _request(QUERY_VISIT_BY_ID, {"id": visit_id})
    if err:
        return None, err
    visit = (data or {}).get("visit")
    return visit, None


# -----------------------------------------------------------------------------
# Get client's properties (need propertyId for job creation)
# -----------------------------------------------------------------------------
# Client has clientProperties(after, before, first, last): PropertyConnection!
# PropertyConnection has both nodes and edges; request nodes for simpler parsing.

QUERY_CLIENT_PROPERTIES = """
query ClientProperties($id: EncodedId!) {
  client(id: $id) {
    id
    clientProperties(first: 10) {
      nodes {
        id
      }
      edges {
        node {
          id
        }
      }
    }
  }
}
"""


def get_client_properties(client_id):
    """
    Get a client's properties. Returns (first property id, list of property dicts, error).
    """
    data, err = _request(QUERY_CLIENT_PROPERTIES, {"id": client_id})
    if err:
        return None, [], err
    client = data.get("client")
    if not client:
        return None, [], "Client not found"
    conn = client.get("clientProperties") or {}
    # PropertyConnection may expose nodes[] or edges[].node; accept both
    nodes = conn.get("nodes")
    if not nodes:
        edges = conn.get("edges") or []
        nodes = [e.get("node") for e in edges if e.get("node")]
    nodes = [n for n in nodes if n and n.get("id")]
    prop_id = nodes[0].get("id") if nodes else None
    if not prop_id:
        # Always print so it shows in runserver console (logging may be disabled)
        print("[Jobber] clientProperties empty for client_id=%s. Full GraphQL data: %s" % (client_id, json.dumps(data, default=str)))
        logger.info("Jobber clientProperties empty (client_id=%s). Raw client: %s", client_id, client)
    return prop_id, nodes, None


# -----------------------------------------------------------------------------
# Create property for a client (service address)
# -----------------------------------------------------------------------------
# propertyCreate(clientId!, input: PropertyCreateInput!) with properties[].address.

MUTATION_PROPERTY_CREATE = """
mutation PropertyCreate($clientId: EncodedId!, $input: PropertyCreateInput!) {
  propertyCreate(clientId: $clientId, input: $input) {
    properties {
      id
    }
    userErrors {
      message
      path
    }
  }
}
"""


def create_property_for_client(client_id, street1, city, province, postal_code, street2=None):
    """
    Create a property (service address) for an existing Jobber client.

    Args:
        client_id: Jobber client encoded ID.
        street1: Street address line 1.
        city: City.
        province: State / province / region.
        postal_code: Postal or ZIP code.
        street2: Optional street line 2.

    Returns:
        (first created property dict with id, or None, error_message).
    """
    address = {
        "street1": (street1 or "").strip(),
        "city": (city or "").strip(),
        "province": (province or "").strip(),
        "postalCode": (postal_code or "").strip(),
    }
    if street2:
        address["street2"] = (street2 or "").strip()
    input_obj = {
        "properties": [
            {"address": address}
        ]
    }
    data, err = _request(MUTATION_PROPERTY_CREATE, {"clientId": client_id, "input": input_obj})
    if err:
        return None, err
    result = data.get("propertyCreate") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        msg = "; ".join([e.get("message", str(e)) for e in user_errors])
        return None, msg
    properties = result.get("properties") or []
    if not properties:
        return None, "No property returned from Jobber"
    prop = properties[0]
    return prop, None


# -----------------------------------------------------------------------------
# Create job (one-off job: propertyId, invoicing, title, lineItems, etc.)
# -----------------------------------------------------------------------------
# JobCreateAttributes: propertyId!, invoicing!, title, instructions, lineItems,
# timeframe, scheduling, notes, etc. No clientId or nested "attributes".

MUTATION_JOB_CREATE = """
mutation JobCreate($input: JobCreateAttributes!) {
  jobCreate(input: $input) {
    job {
      id
      jobNumber
      title
    }
    userErrors {
      message
      path
    }
  }
}
"""


def create_job(
    property_id,
    title,
    line_item_name=None,
    line_item_description=None,
    line_item_price=None,
    job_notes=None,
    scheduled_start_iso=None,
    invoicing=None,
    line_items=None,
):
    """
    Create a one-off job in Jobber.

    Args:
        property_id: Jobber property encoded ID (from get_client_properties(client_id)).
        title: Job title (e.g. "Residential First Clean", "Move-In Cleaning").
        line_item_name: Package/service name (e.g. "Basic Package") — used when line_items is omitted.
        line_item_description: Full package details / cleaning inclusions.
        line_item_price: Approved quote total (decimal/float) — used when line_items is omitted.
        job_notes: Optional job instructions/notes.
        scheduled_start_iso: Optional ISO 8601 datetime for the visit.
        invoicing: Required by Jobber. Defaults to fixed one-time. Pass dict from GraphiQL
                  JobInvoicingAttributes if needed (e.g. billingType, invoiceSchedule).
        line_items: Optional list of dicts: name, description (optional), unit_price, quantity (optional).
                    When provided, builds multiple Jobber line items (multi-service booking).

    Returns:
        (job dict or None, error_message).
    """
    if not property_id:
        return None, "property_id is required (get it from get_client_properties(client_id))"

    built_line_items = []
    if line_items:
        for li in line_items:
            if not isinstance(li, dict):
                return None, "Each line_items entry must be an object"
            name = (li.get("name") or "").strip() or "Service"
            desc = (li.get("description") or "").strip()
            try:
                up = float(li.get("unit_price"))
            except (TypeError, ValueError):
                return None, f"line_items entry must include numeric unit_price: {li!r}"
            qty = li.get("quantity", 1)
            try:
                qty = int(qty)
            except (TypeError, ValueError):
                qty = 1
            if qty < 1:
                qty = 1
            built_line_items.append(
                {
                    "name": name,
                    "description": desc,
                    "unitPrice": round(up, 2),
                    "quantity": qty,
                    "category": "SERVICE",
                    "saveToProductsAndServices": False,
                }
            )
        if not built_line_items:
            return None, "line_items must not be empty"
    else:
        try:
            price_float = float(line_item_price)
        except (TypeError, ValueError):
            return None, "line_item_price must be a number"
        built_line_items = [
            {
                "name": line_item_name or "Service",
                "description": line_item_description or "",
                "unitPrice": round(price_float, 2),
                "quantity": 1,
                "category": "SERVICE",
                "saveToProductsAndServices": False,
            }
        ]

    # Jobber: invoicingType = BillingStrategy (FIXED_PRICE | VISIT_BASED),
    #         invoicingSchedule = BillingFrequencyEnum (ON_COMPLETION | PERIODIC | PER_VISIT | NEVER).
    if invoicing is None:
        invoicing = {
            "invoicingType": "FIXED_PRICE",
            "invoicingSchedule": "ON_COMPLETION",
        }
    # Ensure required invoicing fields exist (allow caller to override)
    invoicing = dict(invoicing)
    if invoicing.get("invoicingType") is None:
        invoicing["invoicingType"] = "FIXED_PRICE"
    if invoicing.get("invoicingSchedule") is None:
        invoicing["invoicingSchedule"] = "ON_COMPLETION"

    # Line items use 'name' (not 'title') and require saveToProductsAndServices.
    input_obj = {
        "propertyId": property_id,
        "invoicing": invoicing,
        "title": title or "Cleaning Job",
        "lineItems": built_line_items,
    }
    # instructions = schedule instructions; notes = array of JobCreateNoteInput (Internal notes / Note details).
    if job_notes:
        input_obj["instructions"] = job_notes
        input_obj["notes"] = [{"message": job_notes}]
    if scheduled_start_iso:
        # TimeframeAttributes: often startAt + duration, or startDate. Try common shape.
        input_obj["timeframe"] = {"startAt": scheduled_start_iso}

    data, err = _request(MUTATION_JOB_CREATE, {"input": input_obj})
    if err:
        return None, err
    result = data.get("jobCreate") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        msg = "; ".join([e.get("message", str(e)) for e in user_errors])
        return None, msg
    job = result.get("job")
    return job, None


# -----------------------------------------------------------------------------
# Client tags (sync with GHL contact tags)
# Jobber Tag type exposes `label` (not `name`) in current GraphQL API versions.
# -----------------------------------------------------------------------------

QUERY_CLIENT_TAG_SYNC = """
query ClientTagSync($id: EncodedId!) {
  client(id: $id) {
    id
    firstName
    lastName
    emails { address }
    phones { number }
    tags(first: 100) {
      nodes {
        id
        label
      }
    }
  }
}
"""

QUERY_ACCOUNT_TAGS = """
query JobberAccountTags {
  account {
    tags(first: 250) {
      nodes {
        id
        label
      }
    }
  }
}
"""

QUERY_ROOT_TAGS = """
query JobberRootTags {
  tags(first: 250) {
    nodes {
      id
      label
    }
  }
}
"""

MUTATION_CLIENT_UPDATE = """
mutation ClientUpdateTags($input: ClientUpdateInput!) {
  clientUpdate(input: $input) {
    client {
      id
      tags(first: 100) {
        nodes {
          id
          label
        }
      }
    }
    userErrors {
      message
      path
    }
  }
}
"""


def _tag_node_display_name(node):
    if not node or not isinstance(node, dict):
        return ""
    return (node.get("label") or node.get("name") or "").strip()


def get_client_for_tag_sync(client_id):
    """
    Fetch Jobber client with emails, phones, and tags.
    Returns (client dict or None, error_message).
    """
    data, err = _request(QUERY_CLIENT_TAG_SYNC, {"id": client_id})
    if err:
        return None, err
    client = (data or {}).get("client")
    if not client:
        return None, "Client not found"
    return client, None


def get_account_tag_name_to_id():
    """
    Map lowercased tag name -> Jobber tag id for the connected account.
    Returns dict (may be empty if query shape differs).
    """
    last_err = None
    for q in (QUERY_ACCOUNT_TAGS, QUERY_ROOT_TAGS):
        data, err = _request(q)
        if err:
            last_err = err
            logger.warning("Jobber account tags query failed: %s", err)
            continue
        conn = None
        acc = (data or {}).get("account")
        if isinstance(acc, dict):
            conn = acc.get("tags")
        if not conn and isinstance((data or {}).get("tags"), dict):
            conn = data.get("tags")
        if not conn:
            continue
        nodes = conn.get("nodes") or []
        out = {}
        for n in nodes:
            tid = n.get("id")
            nm = _tag_node_display_name(n)
            if tid and nm:
                out[nm.lower()] = tid
        if out:
            return out
    if last_err:
        logger.warning("Jobber account tags: no nodes resolved; last query error: %s", last_err)
    return {}


def get_client_tag_label_to_id(client_id):
    """
    Map lowercased label -> tag id from tags already on this client.
    Helps when account-level tag listing returns empty but client tags are present.
    """
    if not client_id:
        return {}
    client, err = get_client_for_tag_sync(client_id)
    if err or not client:
        return {}
    nodes = ((client.get("tags") or {}).get("nodes")) or []
    out = {}
    for n in nodes:
        tid = n.get("id")
        nm = _tag_node_display_name(n)
        if tid and nm:
            out[nm.lower()] = tid
    return out


def list_client_tag_names(client_id):
    """Return sorted list of tag display names for a client."""
    client, err = get_client_for_tag_sync(client_id)
    if err or not client:
        return [], err or "Client not found"
    nodes = ((client.get("tags") or {}).get("nodes")) or []
    names = []
    for n in nodes:
        nm = _tag_node_display_name(n)
        if nm:
            names.append(nm)
    return sorted(set(names)), None


def set_client_tags_by_names(client_id, tag_names):
    """
    Replace Jobber client tags to match the given display names (best effort).
    Resolves names to ids via account tag list; names with no matching Jobber tag are skipped.

    Returns (True, None) or (False, error_message).
    """
    if not client_id:
        return False, "client_id is required"
    tag_names = tag_names or []
    account_map = get_account_tag_name_to_id()
    client_map = get_client_tag_label_to_id(client_id)
    # Account catalog wins on key collision; client map fills gaps (e.g. account query unavailable).
    name_to_id = {**client_map, **account_map}
    if not name_to_id and tag_names:
        return (
            False,
            "Could not load Jobber tags (account tag list and client tags empty); "
            "cannot map tag names to ids. Check Jobber GraphQL access and tag queries.",
        )
    tag_ids = []
    seen = set()
    for raw in tag_names:
        nm = str(raw).strip()
        if not nm:
            continue
        tid = name_to_id.get(nm.lower())
        if not tid:
            logger.warning("Jobber tag name not found in account, skipping: %s", nm)
            continue
        if tid not in seen:
            seen.add(tid)
            tag_ids.append(tid)
    input_obj = {"id": client_id, "tagIds": tag_ids}
    data, err = _request(MUTATION_CLIENT_UPDATE, {"input": input_obj})
    if err:
        # Retry with clientId if schema uses that field name
        input_obj_alt = {"clientId": client_id, "tagIds": tag_ids}
        data, err = _request(MUTATION_CLIENT_UPDATE, {"input": input_obj_alt})
    if err:
        return False, err
    result = (data or {}).get("clientUpdate") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        msg = "; ".join([e.get("message", str(e)) for e in user_errors])
        return False, msg
    return True, None


# -----------------------------------------------------------------------------
# Client notes (internal notes — sync from GHL CRM notes)
# ClientNote text field is typically `message` (align with JobCreate notes shape).
# -----------------------------------------------------------------------------

QUERY_CLIENT_NOTES_MESSAGES = """
query ClientNotesMessages($id: EncodedId!) {
  client(id: $id) {
    id
    notes(first: 100) {
      nodes {
        message
      }
    }
  }
}
"""

MUTATION_CLIENT_CREATE_NOTE = """
mutation ClientCreateNote($clientId: EncodedId!, $input: ClientCreateNoteInput!) {
  clientCreateNote(clientId: $clientId, input: $input) {
    clientNote {
      id
      message
    }
    userErrors {
      message
      path
    }
  }
}
"""


def _note_node_text(node):
    if not node or not isinstance(node, dict):
        return ""
    return str(node.get("message") or node.get("body") or node.get("content") or "").strip()


def list_client_note_messages(client_id):
    """
    Return ordered list of existing client note bodies (for merge before replace).
    """
    if not client_id:
        return [], "client_id is required"
    data, err = _request(QUERY_CLIENT_NOTES_MESSAGES, {"id": client_id})
    if err:
        return [], err
    client = (data or {}).get("client")
    if not client:
        return [], "Client not found"
    nodes = ((client.get("notes") or {}).get("nodes")) or []
    out = []
    for n in nodes:
        t = _note_node_text(n)
        if t:
            out.append(t)
    return out, None


def create_client_note(client_id, message):
    """Create one Jobber client note via clientCreateNote."""
    if not client_id:
        return False, "client_id is required"
    msg = str(message or "").strip()
    if not msg:
        return False, "message is required"
    data, err = _request(
        MUTATION_CLIENT_CREATE_NOTE,
        {"clientId": client_id, "input": {"message": msg[:15000]}},
    )
    if err:
        return False, err
    result = (data or {}).get("clientCreateNote") or {}
    user_errors = result.get("userErrors") or []
    if user_errors:
        msg = "; ".join([e.get("message", str(e)) for e in user_errors])
        return False, msg
    return True, None


def append_ghl_note_to_jobber_client(client_id, ghl_note_id, note_body, *, max_total_chars=28000):
    """
    Append one GHL note as a new Jobber client note.
    Idempotency is enforced by DB-level dedupe in note_sync.

    Returns (success, error_message_or_None, did_write_to_jobber).
    """
    if not client_id:
        return False, "client_id is required", False
    body = (note_body or "").strip()
    if not body:
        return False, "Empty note body", False
    block = body
    if len(block) > max_total_chars:
        block = block[-max_total_chars:]
    ok, uerr = create_client_note(client_id, block)
    return ok, uerr, bool(ok)
