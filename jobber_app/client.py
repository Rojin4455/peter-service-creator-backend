"""
Jobber GraphQL API client.
Uses stored JobberAuthCredentials from accounts app.
"""
import requests
from django.conf import settings

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
        msg = "; ".join(e.get("message", str(e)) for e in user_errors)
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
