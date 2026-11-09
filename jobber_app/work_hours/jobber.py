"""Jobber GraphQL: read timesheet entries (uses existing token refresh) with backoff on throttling."""

import logging
import re
import time

import requests

from jobber_app.client import _request

logger = logging.getLogger(__name__)

PAGE_SIZE = 100
MAX_PAGES = 200
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2

QUERY_TIME_SHEET_ENTRIES = """
query WorkHoursTimeSheetEntries(
  $first: Int!
  $after: String
  $filter: TimeSheetEntriesFilterAttributes
  $sort: [TimeSheetEntriesSortAttributes!]
) {
  timeSheetEntries(first: $first, after: $after, filter: $filter, sort: $sort) {
    nodes {
      id
      startAt
      endAt
      finalDuration
      ticking
      timeSheetCategory
      user { id }
      job { id }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def _is_retryable(err):
    """HTTP 429, Jobber THROTTLED errors and 5xx are worth retrying."""
    msg = (err or "").lower()
    return "http 429" in msg or "throttl" in msg or bool(re.search(r"http 5\d\d", msg))


def _request_with_backoff(query, variables):
    """_request with exponential backoff. Returns (data, error)."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data, err = _request(query, variables)
        except requests.RequestException as exc:
            data, err = None, f"Jobber unreachable: {exc}"
            retryable = True
        else:
            if not err:
                return data, None
            retryable = _is_retryable(err)
        if not retryable or attempt == MAX_ATTEMPTS:
            return None, err
        delay = BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)
        logger.warning(
            "Jobber query failed (attempt %s/%s), retrying in %ss: %s",
            attempt, MAX_ATTEMPTS, delay, err,
        )
        time.sleep(delay)
    return None, "unreachable"


def fetch_time_sheet_entries(start_after, start_before):
    """
    All timesheet entries with startAt in [start_after, start_before) (aware datetimes).

    Returns (entries, error). On error, entries is [] — callers must not treat that as "no hours".
    """
    variables = {
        "first": PAGE_SIZE,
        "filter": {
            "startAt": {
                "after": start_after.isoformat(),
                "before": start_before.isoformat(),
            }
        },
        "sort": [{"field": "START_AT", "direction": "ASCENDING"}],
    }
    entries = []
    for _ in range(MAX_PAGES):
        data, err = _request_with_backoff(QUERY_TIME_SHEET_ENTRIES, dict(variables))
        if err:
            return [], err
        conn = (data or {}).get("timeSheetEntries") or {}
        entries.extend(conn.get("nodes") or [])
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return entries, None
        if not page.get("endCursor"):
            return [], "Jobber returned hasNextPage without endCursor"
        variables["after"] = page["endCursor"]
    return [], f"Timesheet paging exceeded {MAX_PAGES} pages"
