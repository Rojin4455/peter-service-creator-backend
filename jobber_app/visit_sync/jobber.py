"""Jobber GraphQL reads for the visits sync (existing token refresh + throttle backoff)."""

import json
import logging
import time
from decimal import Decimal

from jobber_app.work_hours.jobber import _request_with_backoff

logger = logging.getLogger(__name__)

PAGE_SIZE = 20
MAX_PAGES = 100
PAGE_PAUSE_SECONDS = 1.5
INVOICE_VISITS_LIMIT = 100


class JobberFetchError(Exception):
    pass


# Visit.lineItems returns the job's CURRENT line items (not the billed price), so the invoice
# is the source of truth once a visit is invoiced; line items are only an estimate / split weight.
VISIT_FIELDS = """
  id
  startAt
  visitStatus
  completedAt
  assignedUsers { nodes { id } }
  lineItems(first: 50) { nodes { totalPrice } }
  client { id name }
  job {
    id
    jobNumber
    title
    billingType
    invoiceSchedule { billingFrequency }
  }
  invoice {
    id
    amounts { subtotal discountAmount tipsTotal }
    visits(first: 1) { totalCount }
  }
"""

QUERY_VISIT = "query VisitSyncVisit($id: EncodedId!) { visit(id: $id) { %s } }" % VISIT_FIELDS

QUERY_UPDATED_INVOICES = """
query VisitSyncUpdatedInvoices($first: Int!, $after: String, $filter: InvoiceFilterAttributes) {
  invoices(first: $first, after: $after, filter: $filter) {
    nodes {
      id
      visits(first: %d) { nodes { id } }
    }
    pageInfo { hasNextPage endCursor }
  }
}
""" % INVOICE_VISITS_LIMIT

QUERY_INVOICE_VISITS = """
query VisitSyncInvoiceVisits($id: EncodedId!) {
  invoice(id: $id) {
    id
    visits(first: %d) {
      totalCount
      nodes { id lineItems(first: 50) { nodes { totalPrice } } }
    }
  }
}
""" % INVOICE_VISITS_LIMIT


def _paginate(build_query, variables, root):
    nodes, after = [], None
    for _ in range(MAX_PAGES):
        page_vars = dict(variables)
        if after:
            page_vars["after"] = after
        data, err = _request_with_backoff(build_query(after), page_vars)
        if err:
            raise JobberFetchError(err)
        conn = (data or {}).get(root) or {}
        nodes.extend(conn.get("nodes") or [])
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return nodes
        after = page.get("endCursor")
        if not after:
            raise JobberFetchError("Jobber returned hasNextPage without endCursor")
        # Pace the pages so a long window doesn't drain Jobber's query-cost budget in one burst.
        time.sleep(PAGE_PAUSE_SECONDS)
    raise JobberFetchError(f"Paging {root} exceeded {MAX_PAGES} pages")


def fetch_window_visits(start_after, start_before):
    """All visits with startAt in [start_after, start_before) (aware datetimes)."""
    # The visits filter is written inline, as in jobber_app.client.get_visits.
    window = 'filter: { startAt: { after: %s, before: %s } }' % (
        json.dumps(start_after.isoformat()), json.dumps(start_before.isoformat())
    )

    def build(_after):
        return (
            "query VisitSyncWindow($first: Int!, $after: String) { "
            "visits(first: $first, after: $after, %s) { nodes { %s } pageInfo { hasNextPage endCursor } } }"
            % (window, VISIT_FIELDS)
        )

    return _paginate(build, {"first": PAGE_SIZE}, "visits")


def fetch_updated_invoice_visit_ids(updated_after, updated_before):
    """Visit IDs on invoices updated in [updated_after, updated_before)."""
    variables = {
        "first": 50,
        "filter": {"updatedAt": {"after": updated_after.isoformat(), "before": updated_before.isoformat()}},
    }
    invoices = _paginate(lambda _a: QUERY_UPDATED_INVOICES, variables, "invoices")
    ids = []
    for inv in invoices:
        ids.extend(n["id"] for n in (inv.get("visits") or {}).get("nodes") or [] if n.get("id"))
    return ids


def fetch_visit(visit_id):
    """One visit by ID, or None when Jobber no longer has it (deleted)."""
    data, err = _request_with_backoff(QUERY_VISIT, {"id": visit_id})
    if err:
        msg = err.lower()
        if "not found" in msg or "could not find" in msg or "does not exist" in msg:
            return None
        raise JobberFetchError(err)
    return (data or {}).get("visit")


def fetch_invoice_line_weights(invoice_id):
    """
    {visit_id: line-items total} for every visit on the invoice, used to split it.
    Returns None (with a warning) when the invoice can't be read completely.
    """
    data, err = _request_with_backoff(QUERY_INVOICE_VISITS, {"id": invoice_id})
    if err:
        logger.warning("Visits sync: could not read invoice %s visits: %s", invoice_id, err)
        return None
    conn = (((data or {}).get("invoice") or {}).get("visits")) or {}
    nodes = conn.get("nodes") or []
    if not nodes or conn.get("totalCount") != len(nodes):
        logger.warning(
            "Visits sync: invoice %s lists %s visits, read %s", invoice_id, conn.get("totalCount"), len(nodes)
        )
        return None
    return {
        n["id"]: sum(Decimal(str(li.get("totalPrice") or 0)) for li in (n.get("lineItems") or {}).get("nodes") or [])
        for n in nodes
    }
