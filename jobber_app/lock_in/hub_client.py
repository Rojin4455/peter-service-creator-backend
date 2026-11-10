"""HTTP client: service-creator → Hub lock-in APIs. No Jobber OAuth in Hub."""

import logging

import requests
from decouple import config

logger = logging.getLogger(__name__)


def _base():
    return (config("HUB_BASE_URL", default="") or "").rstrip("/")


class HubLockInError(Exception):
    pass


def _request(method, path, *, json=None, params=None):
    base = _base()
    if not base:
        raise HubLockInError("HUB_BASE_URL is not configured")
    # Same shared secret as the visits / work-hours upserts; the Hub requires it on all internal endpoints.
    secret = config("HUB_INTERNAL_SECRET", default="") or ""
    if not secret:
        raise HubLockInError("HUB_INTERNAL_SECRET is not configured")
    url = f"{base}{path}"
    try:
        resp = requests.request(
            method,
            url,
            json=json,
            params=params,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Internal-Secret": secret,
            },
            timeout=30,
        )
    except requests.RequestException as exc:
        raise HubLockInError(f"Hub unreachable: {exc}") from exc
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        # Error bodies may not be a JSON object (HTML page, bare string): never let that crash callers.
        detail = (
            (data.get("detail") or data.get("error")) if isinstance(data, dict) else None
        ) or resp.text[:400]
        hint = " (check HUB_INTERNAL_SECRET matches the Hub's secret)" if resp.status_code in (401, 403) else ""
        raise HubLockInError(f"Hub HTTP {resp.status_code}: {detail}{hint}")
    return data


def upsert_visit(payload):
    return _request("POST", "/api/internal/lock-in/visits/upsert/", json=payload)


def list_visits(*, jobber_visit_ids=None, client_id=None):
    params = {}
    if jobber_visit_ids:
        params["jobber_visit_ids"] = ",".join(str(x) for x in jobber_visit_ids)
    if client_id:
        params["client_id"] = client_id
    return _request("GET", "/api/internal/lock-in/visits/", params=params)


def create_pending(payload):
    return _request("POST", "/api/internal/lock-in/pending/", json=payload)


def lookup_pending(client_id, job_id=None):
    params = {"client_id": client_id}
    if job_id:
        params["job_id"] = job_id
    return _request("GET", "/api/internal/lock-in/pending/lookup/", params=params)


def confirm_pending(pending_id, *, visit_id, visit_at=None):
    return _request(
        "POST",
        f"/api/internal/lock-in/pending/{pending_id}/confirm/",
        json={"visit_id": visit_id, "visit_at": visit_at},
    )


def expire_pending(pending_id, reason="Eligibility Period Exceeded"):
    return _request(
        "POST",
        f"/api/internal/lock-in/pending/{pending_id}/expire/",
        json={"reason": reason},
    )


def mark_bonus_sms(bonus_id, **flags):
    return _request("PATCH", f"/api/internal/lock-in/bonuses/{bonus_id}/sms/", json=flags)


def patch_pending(pending_id, payload):
    return _request(
        "PATCH",
        f"/api/internal/lock-in/pending/{pending_id}/",
        json=payload,
    )


def set_user_ghl_id(user_id, ghl_id):
    return _request(
        "PATCH",
        f"/api/internal/lock-in/users/{user_id}/",
        json={"ghl_id": ghl_id},
    )
