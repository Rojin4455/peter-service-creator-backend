"""Jobber GraphQL helpers for lock-in (uses existing token refresh)."""

import logging

from jobber_app.client import _request, get_job_visits

logger = logging.getLogger(__name__)

QUERY_QUOTE = """
query LockInQuote($id: EncodedId!) {
  quote(id: $id) {
    id
    createdAt
    client {
      id
      firstName
      lastName
      name
    }
  }
}
"""

QUERY_CLIENT_JOBS = """
query LockInClientJobs($id: EncodedId!) {
  client(id: $id) {
    id
    name
    jobs(first: 100) {
      nodes {
        id
        title
      }
      edges {
        node {
          id
          title
        }
      }
    }
  }
}
"""

QUERY_VISIT_LOCK_IN = """
query LockInVisit($id: EncodedId!) {
  visit(id: $id) {
    id
    title
    startAt
    endAt
    client {
      id
      name
    }
    assignedUsers {
      nodes {
        id
        name { full }
      }
    }
    job {
      id
      title
      jobType
    }
  }
}
"""

QUERY_JOB_VISITS_ASSIGNEES = """
query LockInJobVisits($id: EncodedId!) {
  job(id: $id) {
    id
    title
    jobType
    visits(first: 100) {
      nodes {
        id
        title
        startAt
        assignedUsers {
          nodes {
            id
            name { full }
          }
        }
      }
    }
  }
}
"""


def get_quote(quote_id):
    data, err = _request(QUERY_QUOTE, {"id": quote_id})
    if err:
        return None, err
    return (data or {}).get("quote"), None


def get_client_jobs(client_id):
    data, err = _request(QUERY_CLIENT_JOBS, {"id": client_id})
    if err:
        return [], err
    client = (data or {}).get("client") or {}
    jobs = client.get("jobs") or {}
    nodes = jobs.get("nodes")
    if not nodes:
        nodes = [e.get("node") for e in (jobs.get("edges") or []) if e.get("node")]
    return nodes or [], None


def get_visit_lock_in(visit_id):
    data, err = _request(QUERY_VISIT_LOCK_IN, {"id": visit_id})
    if err:
        return None, err
    return (data or {}).get("visit"), None


def get_job_visits_with_assignees(job_id):
    data, err = _request(QUERY_JOB_VISITS_ASSIGNEES, {"id": job_id})
    if err:
        return None, err
    return (data or {}).get("job"), None


def list_job_visits(job_id):
    visits, err = get_job_visits(job_id)
    return visits, err
