"""
Jobber GraphQL API client.
Uses stored JobberAuthCredentials from accounts app.
"""
import json
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

JOBBER_GRAPHQL_URL = "https://api.getjobber.com/api/graphql"


def get_access_token():
    """Get current Jobber access token from DB. Caller should handle refresh if 401."""
    from accounts.models import JobberAuthCredentials
    creds = JobberAuthCredentials.objects.first()
    if not creds:
        return None
    return creds.access_token


def _request(query, variables=None):
    """POST a GraphQL request to Jobber. Returns (data dict, error message or None)."""
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
    if resp.status_code != 200:
        return None, f"Jobber API HTTP {resp.status_code}: {resp.text[:500]}"
    data = resp.json()
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
        input_obj["phones"] = [{"number": str(phone), "primary": True, "description": "MAIN"}]
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
    line_item_name,
    line_item_description,
    line_item_price,
    job_notes=None,
    scheduled_start_iso=None,
    invoicing=None,
):
    """
    Create a one-off job in Jobber.

    Args:
        property_id: Jobber property encoded ID (from get_client_properties(client_id)).
        title: Job title (e.g. "Residential First Clean", "Move-In Cleaning").
        line_item_name: Package/service name (e.g. "Basic Package").
        line_item_description: Full package details / cleaning inclusions.
        line_item_price: Approved quote total (decimal/float).
        job_notes: Optional job instructions/notes.
        scheduled_start_iso: Optional ISO 8601 datetime for the visit.
        invoicing: Required by Jobber. Defaults to fixed one-time. Pass dict from GraphiQL
                  JobInvoicingAttributes if needed (e.g. billingType, invoiceSchedule).

    Returns:
        (job dict or None, error_message).
    """
    try:
        price_float = float(line_item_price)
    except (TypeError, ValueError):
        return None, "line_item_price must be a number"

    if not property_id:
        return None, "property_id is required (get it from get_client_properties(client_id))"

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
        "lineItems": [
            {
                "name": line_item_name or "Service",
                "description": line_item_description or "",
                "unitPrice": round(price_float, 2),
                "quantity": 1,
                "category": "SERVICE",
                "saveToProductsAndServices": False,
            }
        ],
    }
    if job_notes:
        input_obj["instructions"] = job_notes
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
