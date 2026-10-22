"""HTTP client: service-creator → Hub work-hours upsert (shared-secret auth, retries)."""

import logging
import time

import requests
from decouple import config

logger = logging.getLogger(__name__)

UPSERT_PATH = "/api/internal/work-hours/upsert/"
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2
MAX_RETRY_AFTER_SECONDS = 60
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HubWorkHoursError(Exception):
    pass


def _retry_delay(attempt, resp=None):
    if resp is not None:
        retry_after = (resp.headers.get("Retry-After") or "").strip()
        if retry_after.isdigit():
            return min(int(retry_after), MAX_RETRY_AFTER_SECONDS)
    return BACKOFF_BASE_SECONDS * 2 ** (attempt - 1)


def upsert_work_hours(entries):
    """
    POST one batch of work-hours rows. Safe to retry: the Hub overwrites each user-day.

    Returns the Hub response dict ({"saved", "skipped", "skipped_ids", "invalid"}).
    Raises HubWorkHoursError when not configured, on non-retryable errors, or after retries.
    """
    base = (config("HUB_BASE_URL", default="") or "").rstrip("/")
    secret = config("HUB_INTERNAL_SECRET", default="") or ""
    if not base:
        raise HubWorkHoursError("HUB_BASE_URL is not configured")
    if not secret:
        raise HubWorkHoursError("HUB_INTERNAL_SECRET is not configured")

    url = f"{base}{UPSERT_PATH}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Internal-Secret": secret,
    }
    for attempt in range(1, MAX_ATTEMPTS + 1):
        resp = None
        try:
            resp = requests.post(url, json={"entries": entries}, headers=headers, timeout=60)
        except requests.RequestException as exc:
            err = f"Hub unreachable: {exc}"
        else:
            try:
                data = resp.json() if resp.content else {}
            except ValueError:
                data = {}
            if resp.status_code < 400:
                return data
            detail = (
                (data.get("detail") or data.get("error")) if isinstance(data, dict) else None
            ) or resp.text[:400]
            err = f"Hub HTTP {resp.status_code}: {detail}"
            if resp.status_code not in RETRY_STATUSES:
                raise HubWorkHoursError(err)
        if attempt == MAX_ATTEMPTS:
            raise HubWorkHoursError(err)
        delay = _retry_delay(attempt, resp)
        logger.warning(
            "Hub work-hours upsert failed (attempt %s/%s), retrying in %ss: %s",
            attempt, MAX_ATTEMPTS, delay, err,
        )
        time.sleep(delay)
    raise HubWorkHoursError("unreachable")
