"""
GoHighLevel (LeadConnector) Calendar API — block slots for syncing Jobber busy times.

Official docs (Marketplace):
- Calendar Events index: https://marketplace.gohighlevel.com/docs/ghl/calendars/calendar-events/index.html
- Create Block Slot: https://marketplace.gohighlevel.com/docs/ghl/calendars/create-block-slot/index.html
- Update Block Slot: https://marketplace.gohighlevel.com/docs/ghl/calendars/edit-block-slot/index.html
- Delete Event: https://marketplace.gohighlevel.com/docs/ghl/calendars/delete-event/index.html
- Scopes (calendars/events.write): https://marketplace.gohighlevel.com/docs/Authorization/Scopes/index.html

Base URL: https://services.leadconnectorhq.com (same as quote_app/helpers.py)

Optional: set GHL_PRIVATE_INTEGRATION_TOKEN (Sub-Account Private Integration Token) to use
Bearer PIT for these calendar calls instead of OAuth rows in GHLAuthCredentials — no refresh flow.
"""
import logging
from datetime import datetime, timezone as dt_timezone

import requests
from decouple import config
from django.utils import dateparse

from accounts.models import GHLAuthCredentials

logger = logging.getLogger(__name__)

GHL_BASE_URL = "https://services.leadconnectorhq.com"
# Match quote_app/helpers.py; HighLevel requires Version on all REST calls.
GHL_API_VERSION = config("GHL_API_VERSION", default="2021-07-28")


def _private_integration_token():
    """Sub-account PIT from env; when set, calendar API uses it instead of OAuth DB credentials."""
    pit = config("GHL_PRIVATE_INTEGRATION_TOKEN", default="").strip()
    if pit:
        return pit
    # Short alias some teams use in .env
    return config("GHL_PIT", default="").strip()


def _get_credentials():
    return GHLAuthCredentials.objects.order_by("-updated_at").first()


def _refresh_access_token(creds):
    """Refresh OAuth token using stored refresh_token (same token URL as accounts.views.tokens)."""
    try:
        client_id = config("GHL_CLIENT_ID")
        client_secret = config("GHL_CLIENT_SECRET")
    except Exception as e:
        return None, f"GHL env not configured: {e}"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": creds.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    resp = requests.post(
        "https://services.leadconnectorhq.com/oauth/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    try:
        body = resp.json()
    except requests.exceptions.JSONDecodeError:
        return None, f"Invalid JSON from GHL token endpoint: {resp.text[:300]}"
    if resp.status_code != 200:
        return None, body.get("error_description") or body.get("error") or resp.text[:300]
    access = body.get("access_token")
    refresh = body.get("refresh_token") or creds.refresh_token
    if not access:
        return None, "Missing access_token in GHL refresh response"
    creds.access_token = access
    creds.refresh_token = refresh
    if body.get("expires_in") is not None:
        creds.expires_in = int(body["expires_in"])
    creds.save(update_fields=["access_token", "refresh_token", "expires_in", "updated_at"])
    return access, None


def _headers_bearer(access_token, *, include_json=True):
    h = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Version": GHL_API_VERSION,
    }
    if include_json:
        h["Content-Type"] = "application/json"
    return h


def _headers(creds, *, include_json=True):
    return _headers_bearer(creds.access_token, include_json=include_json)


def _parse_ghl_response(resp):
    try:
        data = resp.json() if resp.content else {}
    except requests.exceptions.JSONDecodeError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        msg = data.get("message") or data.get("error") or data.get("msg") or str(data)[:500]
        return None, f"GHL API {resp.status_code}: {msg}"
    return data, None


def _request(method, path, *, json=None, _retry=True):
    """
    Call LeadConnector API.

    If GHL_PRIVATE_INTEGRATION_TOKEN (or GHL_PIT) is set, uses Bearer PIT — no OAuth DB row and no refresh.

    Otherwise uses GHLAuthCredentials; on 401, refreshes OAuth once and retries.
    path: e.g. '/calendars/events/block-slots'
    """
    url = f"{GHL_BASE_URL}{path}"
    include_json = method.upper() in ("POST", "PUT", "PATCH")

    pit = _private_integration_token()
    if pit:
        resp = requests.request(
            method,
            url,
            headers=_headers_bearer(pit, include_json=include_json),
            json=json if include_json else None,
            timeout=45,
        )
        if resp.status_code == 401:
            return (
                None,
                "GHL unauthorized (private integration token). Check token value, integration permissions "
                "(calendar events), and that the token is for the correct sub-account.",
            )
        return _parse_ghl_response(resp)

    creds = _get_credentials()
    if not creds:
        return None, "GHL not connected. Complete OAuth at /api/accounts/auth/connect/ (store GHLAuthCredentials), or set GHL_PRIVATE_INTEGRATION_TOKEN."
    resp = requests.request(
        method,
        url,
        headers=_headers(creds, include_json=include_json),
        json=json if include_json else None,
        timeout=45,
    )
    if resp.status_code == 401 and _retry:
        _, err = _refresh_access_token(creds)
        if err:
            return None, f"GHL unauthorized and token refresh failed: {err}"
        creds.refresh_from_db()
        return _request(method, path, json=json, _retry=False)
    return _parse_ghl_response(resp)


def create_block_slot(location_id, calendar_id, start_time_iso, end_time_iso, title=None):
    """
    POST /calendars/events/block-slots
    Body fields per LeadConnector OpenAPI summaries: locationId (required), startTime, endTime,
    calendarId (optional but required for a specific booking calendar), title optional.
    """
    payload = {
        "locationId": location_id,
        "calendarId": calendar_id,
        "startTime": start_time_iso,
        "endTime": end_time_iso,
    }
    if title:
        payload["title"] = title[:500]
    return _request("POST", "/calendars/events/block-slots", json=payload)


def update_block_slot(event_id, location_id, calendar_id, start_time_iso, end_time_iso, title=None):
    """PUT /calendars/events/block-slots/:eventId"""
    payload = {
        "locationId": location_id,
        "calendarId": calendar_id,
        "startTime": start_time_iso,
        "endTime": end_time_iso,
    }
    if title:
        payload["title"] = title[:500]
    return _request("PUT", f"/calendars/events/block-slots/{event_id}", json=payload)


def delete_calendar_event(event_id):
    """DELETE /calendars/events/:eventId (blocks and appointments use same delete path per docs)."""
    return _request("DELETE", f"/calendars/events/{event_id}", json=None)


def parse_iso_datetime(value):
    """Parse Jobber/GHL ISO strings to aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    dt = dateparse.parse_datetime(s)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return dt
