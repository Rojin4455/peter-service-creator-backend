"""
Basic test endpoints for Jobber integration.
"""
import json
import logging
import re
import uuid
from datetime import timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from decouple import config
from django.db.models import Sum
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from quote_app.models import CustomerPackageQuote, CustomerSubmission

from .client import search_clients, create_client, get_visits, create_job, get_client_properties, create_property_for_client
from .models import GhlAppointmentJobberJobMap
from .sync_ghl_calendar import (
    delete_jobber_visit_from_ghl_blocks,
    sync_jobber_job_to_ghl_blocks,
    sync_jobber_visit_to_ghl_blocks,
    sync_jobber_visits_to_ghl_blocks,
)
from .note_sync import sync_ghl_note_to_jobber
from .tag_sync import sync_ghl_contact_tags_to_jobber, sync_jobber_client_tags_to_ghl

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

logger = logging.getLogger(__name__)


def _ghl_calendar_map_defaults_from_cal(cal):
    """Build GhlAppointmentJobberJobMap time fields from workflow `calendar` JSON."""
    defaults = {
        "raw_start_time_iso": "",
        "raw_end_time_iso": "",
        "calendar_timezone": "",
        "booking_start_at": None,
        "booking_end_at": None,
    }
    if not isinstance(cal, dict):
        return defaults
    start_raw = (cal.get("startTime") or cal.get("start_time") or "").strip()
    end_raw = (cal.get("endTime") or cal.get("end_time") or "").strip()
    tz_name = (cal.get("selectedTimezone") or cal.get("timezone") or "").strip()
    if start_raw:
        defaults["raw_start_time_iso"] = start_raw[:80]
    if end_raw:
        defaults["raw_end_time_iso"] = end_raw[:80]
    if tz_name:
        defaults["calendar_timezone"] = tz_name[:128]

    def _to_utc(s):
        if not s:
            return None
        dt = parse_datetime(str(s).strip().replace("Z", "+00:00"))
        if dt is None:
            return None
        if timezone.is_naive(dt):
            if tz_name and ZoneInfo is not None:
                try:
                    dt = timezone.make_aware(dt, ZoneInfo(tz_name))
                except Exception:
                    dt = timezone.make_aware(dt, timezone.get_current_timezone())
            else:
                dt = timezone.make_aware(dt, dt_timezone.utc)
        return dt.astimezone(dt_timezone.utc)

    defaults["booking_start_at"] = _to_utc(start_raw)
    defaults["booking_end_at"] = _to_utc(end_raw)
    return defaults


class JobberSearchClientsView(APIView):
    """GET ?search=email_or_phone - Search for clients in Jobber."""
    permission_classes = [AllowAny]

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        if not search:
            return Response(
                {"error": "Query param 'search' required (email or phone)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        first = min(int(request.query_params.get("first", 5)), 20)
        nodes, total_count, err = search_clients(search, first=first)
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({
            "totalCount": total_count,
            "nodes": nodes,
        })


class JobberCreateClientView(APIView):
    """POST { first_name, last_name, email?, phone? } - Create a client in Jobber."""
    permission_classes = [AllowAny]

    def post(self, request):
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        email = request.data.get("email", "").strip() or None
        phone = request.data.get("phone", "").strip() or None
        if not first_name or not last_name:
            return Response(
                {"error": "first_name and last_name are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not email and not phone:
            return Response(
                {"error": "At least one of email or phone is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        client, err = create_client(first_name, last_name, email=email, phone=phone)
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"client": client}, status=status.HTTP_201_CREATED)


class JobberVisitsView(APIView):
    """GET ?after=ISO&before=ISO - List visits (busy slots) in Jobber for a date range."""
    permission_classes = [AllowAny]

    def get(self, request):
        after = request.query_params.get("after", "").strip()
        before = request.query_params.get("before", "").strip()
        if not after or not before:
            return Response(
                {"error": "Query params 'after' and 'before' required (ISO 8601, e.g. 2026-04-15T00:00:00Z)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        nodes, err = get_visits(after, before)
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"visits": nodes})


class JobberCreatePropertyView(APIView):
    """
    POST – Create a property (service address) for an existing Jobber client.
    Use when the client has no property so you can create a job for them.

    Body (JSON):
      - client_id (required): Jobber client encoded ID.
      - street1 (required): Street address line 1.
      - city (required): City.
      - province (required): State / province / region.
      - postal_code (required): Postal or ZIP code.
      - street2 (optional): Street address line 2.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        client_id = (request.data.get("client_id") or "").strip()
        street1 = (request.data.get("street1") or "").strip()
        city = (request.data.get("city") or "").strip()
        province = (request.data.get("province") or "").strip()
        postal_code = (request.data.get("postal_code") or "").strip()
        street2 = (request.data.get("street2") or "").strip() or None

        if not client_id:
            return Response(
                {"error": "client_id is required (Jobber client encoded ID)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not street1:
            return Response(
                {"error": "street1 is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not city:
            return Response(
                {"error": "city is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not province:
            return Response(
                {"error": "province is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not postal_code:
            return Response(
                {"error": "postal_code is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        property_obj, err = create_property_for_client(
            client_id=client_id,
            street1=street1,
            city=city,
            province=province,
            postal_code=postal_code,
            street2=street2,
        )
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"property": property_obj}, status=status.HTTP_201_CREATED)


class JobberCreateJobView(APIView):
    """
    POST – Create a one-off job in Jobber.

    Body (JSON):
      - client_id OR property_id (one required): If client_id, we resolve property from client.
      - title (required): Job title (e.g. "Residential First Clean").
      - line_item_name (required): Package name (e.g. "Basic Package").
      - line_item_description (optional): Package details.
      - line_item_price (required): Approved total (number).
      - job_notes (optional): Job instructions/specs.
      - scheduled_start_iso (optional): Visit start, ISO 8601.
      - invoicing (optional): JobInvoicingAttributes; default invoicingType: "FIXED_PRICE", invoicingSchedule: "ON_COMPLETION". Types: FIXED_PRICE|VISIT_BASED; ON_COMPLETION|PERIODIC|PER_VISIT|NEVER.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        client_id = (request.data.get("client_id") or "").strip()
        property_id = (request.data.get("property_id") or "").strip()
        title = (request.data.get("title") or "").strip()
        line_item_name = (request.data.get("line_item_name") or "").strip()
        line_item_description = (request.data.get("line_item_description") or "").strip()
        line_item_price = request.data.get("line_item_price")
        job_notes = (request.data.get("job_notes") or "").strip() or None
        scheduled_start_iso = (request.data.get("scheduled_start_iso") or "").strip() or None
        invoicing = request.data.get("invoicing")

        if not property_id and not client_id:
            return Response(
                {"error": "Either client_id or property_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not title:
            return Response(
                {"error": "title is required (e.g. Residential First Clean)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not line_item_name:
            return Response(
                {"error": "line_item_name is required (e.g. Basic Package)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if line_item_price is None:
            return Response(
                {"error": "line_item_price is required (approved quote total)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not property_id:
            prop_id, _, err = get_client_properties(client_id)
            if err:
                return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
            if not prop_id:
                return Response(
                    {"error": "Client has no property. Create a property for this client in Jobber first."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            property_id = prop_id

        job, err = create_job(
            property_id=property_id,
            title=title,
            line_item_name=line_item_name,
            line_item_description=line_item_description,
            line_item_price=line_item_price,
            job_notes=job_notes,
            scheduled_start_iso=scheduled_start_iso,
            invoicing=invoicing,
        )
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        return Response({"job": job}, status=status.HTTP_201_CREATED)


def _build_booking_job_notes(data):
    """Build job notes string from booking job details (per integration doc)."""
    parts = []
    if data.get("bedrooms") is not None:
        parts.append(f"Bedrooms: {data.get('bedrooms')}")
    if data.get("bathrooms") is not None:
        parts.append(f"Bathrooms: {data.get('bathrooms')}")
    if data.get("square_footage"):
        parts.append(f"Square footage: {data.get('square_footage')}")
    if data.get("condition"):
        parts.append(f"Condition: {data.get('condition')}")
    if data.get("pets"):
        parts.append(f"Pets: {data.get('pets')}")
    if data.get("add_ons"):
        parts.append(f"Add-ons: {data.get('add_ons')}")
    if data.get("special_instructions"):
        parts.append(f"Special requests: {data.get('special_instructions')}")
    if data.get("entry_instructions"):
        parts.append(f"Entry instructions: {data.get('entry_instructions')}")
    if data.get("estimated_labor_hours") is not None:
        parts.append(f"Estimated labor hours: {data.get('estimated_labor_hours')}")
    return "\n".join(parts) if parts else None


def _compute_labor_and_slot(price, service_type="", team_size=2):
    """
    Compute labor hours (low/high) and calendar slot duration per integration doc.
    Residential First Clean: low = price/65, high = price/55.
    Move-In / Move-Out: low = price/75, high = price/65.
    Slot duration = labor_high / team_size, rounded to nearest 0.5 hour.
    Returns (labor_hours_low, labor_hours_high, slot_duration_hours).
    """
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None, None, None
    if p <= 0:
        return None, None, None
    st = (service_type or "").strip().lower()
    if "move" in st or "move-in" in st or "move-out" in st:
        low = p / 75.0
        high = p / 65.0
    else:
        low = p / 65.0
        high = p / 55.0
    try:
        ts = max(1, min(10, int(team_size)))
    except (TypeError, ValueError):
        ts = 2
    slot = high / ts
    slot_rounded = round(slot * 2) / 2.0
    slot_rounded = max(0.5, slot_rounded)
    return round(low, 2), round(high, 2), round(slot_rounded, 2)


def _parse_booking_datetime(selected_date, selected_time, scheduled_start_iso):
    """Return ISO 8601 datetime for job start. Prefer scheduled_start_iso; else combine date + time."""
    if scheduled_start_iso and str(scheduled_start_iso).strip():
        return str(scheduled_start_iso).strip()
    date_str = (selected_date or "").strip()
    time_str = (selected_time or "").strip()
    if not date_str or not time_str:
        return None
    # Allow "2026-04-20" + "14:00" or "14:00:00"
    if "T" in date_str:
        return date_str
    if len(time_str) <= 5 and ":" in time_str:
        time_str = time_str + ":00"  # 14:00 -> 14:00:00
    return f"{date_str}T{time_str}"


def _normalize_booking_services(data):
    """
    Build job title and line_items for Jobber from booking payload.

    Supports:
    - Legacy: service_type (str) + package_title + approved_price → one line item.
    - Multiple: service_types (list of strings) + shared package_title + approved_price
      → equal split across line items (one per service type).
    - Structured: services (list of objects) with per-line pricing:
        { service_type, package_title?, package_description?, line_item_price | price }

    Returns (job_title, line_items_list, error_message_or_None).
    line_items_list items: {name, description, unit_price, quantity?}.
    """
    approved = data.get("approved_price") if data.get("approved_price") is not None else data.get("line_item_price")

    # Structured multi-service rows
    raw_services = data.get("services")
    if isinstance(raw_services, list) and len(raw_services) > 0:
        line_items = []
        titles = []
        for row in raw_services:
            if not isinstance(row, dict):
                return None, None, "Each services[] entry must be an object"
            st = (row.get("service_type") or row.get("title") or "").strip()
            pkg = (row.get("package_title") or row.get("line_item_name") or data.get("package_title") or "").strip()
            desc = (row.get("package_description") or row.get("line_item_description") or data.get("package_description") or "").strip()
            line_price = row.get("line_item_price") if row.get("line_item_price") is not None else row.get("price")
            if st:
                titles.append(st)
            name = pkg or st or "Service"
            if st and pkg and pkg.lower() != st.lower():
                name = f"{pkg} — {st}"
            elif st and not pkg:
                name = st
            if line_price is None:
                return None, None, "Each services[] entry must include line_item_price or price when using services[]"
            try:
                float(line_price)
            except (TypeError, ValueError):
                return None, None, "services[] line_item_price must be numeric"
            line_items.append({"name": name, "description": desc, "unit_price": float(line_price), "quantity": 1})
        job_title = ", ".join(titles) if titles else (data.get("service_type") or "Multi-service")
        return job_title, line_items, None

    # List of service type labels + shared package / total price
    raw_types = data.get("service_types")
    if isinstance(raw_types, list) and len(raw_types) > 0:
        types_clean = []
        for t in raw_types:
            s = str(t).strip() if t is not None else ""
            if s:
                types_clean.append(s)
        if not types_clean:
            return None, None, "service_types must contain at least one non-empty string"
        if approved is None:
            return None, None, "approved_price is required when using service_types[]"
        try:
            total = float(approved)
        except (TypeError, ValueError):
            return None, None, "approved_price must be a number"
        n = len(types_clean)
        share = round(total / n, 2)
        # Fix rounding drift: last line absorbs remainder
        remainder = round(total - share * (n - 1), 2)
        pkg = (data.get("package_title") or data.get("line_item_name") or "").strip()
        desc = (data.get("package_description") or data.get("line_item_description") or "").strip()
        line_items = []
        for i, st in enumerate(types_clean):
            price = remainder if i == n - 1 else share
            name = f"{pkg} ({st})" if pkg else st
            line_items.append({"name": name, "description": desc, "unit_price": price, "quantity": 1})
        job_title = ", ".join(types_clean)
        return job_title, line_items, None

    # Single legacy field
    service_type = (data.get("service_type") or data.get("title") or "").strip()
    if not service_type:
        return None, None, None
    if approved is None:
        return None, None, None
    pkg = (data.get("package_title") or data.get("line_item_name") or "").strip()
    desc = (data.get("package_description") or data.get("line_item_description") or "").strip()
    try:
        float(approved)
    except (TypeError, ValueError):
        return None, None, "approved_price must be a number"
    line_items = [{"name": pkg or service_type, "description": desc, "unit_price": float(approved), "quantity": 1}]
    return service_type, line_items, None


def _booking_confirm_payload_dict(raw):
    """Normalize DRF Request.data / QueryDict into a plain dict for execute_booking_confirm."""
    if raw is None:
        return {}
    if hasattr(raw, "dict"):
        try:
            return dict(raw.dict())
        except Exception:
            pass
    if isinstance(raw, dict):
        return dict(raw)
    try:
        return dict(raw)
    except Exception:
        return {}


def execute_booking_confirm(data):
    """
    Find or create Jobber client → resolve or create property → create job.
    `data` uses the same shape as BookingConfirmView POST JSON.

    Returns:
        (result_dict, None) on success.
        (None, Response) on failure (same status codes as the HTTP API).
    """
    if not isinstance(data, dict):
        data = {}
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    email = (data.get("email") or "").strip() or None
    phone = data.get("phone")
    if phone is not None:
        phone = str(phone).strip() or None
    street1 = (data.get("street1") or data.get("service_address") or "").strip()
    city = (data.get("city") or "").strip()
    province = (data.get("province") or data.get("state") or "").strip()
    postal_code = (data.get("postal_code") or data.get("zip_code") or "").strip()
    street2 = (data.get("street2") or "").strip() or None
    scheduled_start_iso = _parse_booking_datetime(
        data.get("selected_date"),
        data.get("selected_time"),
        data.get("scheduled_start_iso"),
    )
    if not first_name or not last_name:
        return None, Response(
            {"error": "first_name and last_name are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not email and not phone:
        return None, Response(
            {"error": "At least one of email or phone is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    job_title, line_items, norm_err = _normalize_booking_services(data)
    if norm_err:
        return None, Response({"error": norm_err}, status=status.HTTP_400_BAD_REQUEST)
    if not line_items or not job_title:
        return None, Response(
            {
                "error": "Provide service_type (single), service_types (array of strings), or services (array of objects with per-line pricing).",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    has_structured = isinstance(data.get("services"), list) and len(data.get("services") or []) > 0
    has_multi_types = isinstance(data.get("service_types"), list) and len(data.get("service_types") or []) > 0
    if not has_structured and not has_multi_types:
        package_title = (data.get("package_title") or data.get("line_item_name") or "").strip()
        if not package_title:
            return None, Response(
                {"error": "package_title is required (e.g. Basic Package) when using single service_type"},
                status=status.HTTP_400_BAD_REQUEST,
            )

    search_term = email or phone
    nodes, _, err = search_clients(search_term, first=5)
    if err:
        return None, Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
    client_id = None
    client_created = False
    if nodes:
        client_id = nodes[0].get("id")
    if not client_id:
        client, err = create_client(first_name, last_name, email=email, phone=phone)
        if err:
            return None, Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        client_id = client.get("id")
        client_created = True

    prop_id, _, err = get_client_properties(client_id)
    if err:
        return None, Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
    if not prop_id:
        if not street1 or not city or not province or not postal_code:
            return None, Response(
                {"error": "Client has no property. Provide street1, city, province, postal_code to create one."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        prop, err = create_property_for_client(
            client_id=client_id,
            street1=street1,
            city=city,
            province=province,
            postal_code=postal_code,
            street2=street2,
        )
        if err:
            return None, Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        prop_id = prop.get("id")

    job_notes = _build_booking_job_notes(data)
    job, err = create_job(
        property_id=prop_id,
        title=job_title,
        job_notes=job_notes,
        scheduled_start_iso=scheduled_start_iso,
        line_items=line_items,
    )
    if err:
        return None, Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)

    return (
        {
            "client_id": client_id,
            "client_created": client_created,
            "property_id": prop_id,
            "job": job,
        },
        None,
    )


_SUBMISSION_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _extract_submission_uuid_from_quote_url(url):
    """
    Prefer explicit quote/booking URL shapes so we never grab the wrong UUID if the string
    contains more than one UUID.
    """
    if not url:
        return None
    s = str(url).strip()
    m = re.search(r"/quote/details/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", s, re.I)
    if m:
        return m.group(1)
    m = re.search(
        r"submission[_-]?id=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        s,
        re.I,
    )
    if m:
        return m.group(1)
    m = _SUBMISSION_UUID_RE.search(s)
    return m.group(0) if m else None


_QUOTE_SUBMISSION_URL_KEYS = (
    "Quote Submission Url",
    "Quote Submission URL",
    "quote_submission_url",
    "QuoteSubmissionUrl",
    "Quote Details Url",
    "Quote Details URL",
    "quote_details_url",
)


def _first_http_quote_url_from_dict(d):
    if not isinstance(d, dict):
        return None
    for key in _QUOTE_SUBMISSION_URL_KEYS:
        v = d.get(key)
        if v and str(v).strip().lower().startswith("http"):
            return str(v).strip()
    return None


def _http_quote_url_from_dict_values(d):
    """Any value that looks like a quote/booking URL (handles odd GHL customData keys)."""
    if not isinstance(d, dict):
        return None
    for v in d.values():
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s.lower().startswith("http"):
            continue
        low = s.lower()
        if "quote/details/" in low or "submission_id=" in low or "/booking?" in low:
            return s
    return None


def _quote_url_from_attribution(payload):
    """
    GHL sets attributionSource.url (and contact.*) to the page URL for the session that led to
    the calendar booking — e.g. https://site.../quote/details/<uuid> when the widget is embedded
    on the quote page. This is more reliable than contact custom fields or workflow customData,
    which are often empty or stale.
    """
    if not isinstance(payload, dict):
        return None
    blocks = []
    for key in ("attributionSource", "lastAttributionSource"):
        b = payload.get(key)
        if isinstance(b, dict):
            blocks.append(b)
    for contact in (
        payload.get("contact"),
        (payload.get("calendar") or {}).get("contact") if isinstance(payload.get("calendar"), dict) else None,
        (payload.get("appointment") or {}).get("contact") if isinstance(payload.get("appointment"), dict) else None,
    ):
        if isinstance(contact, dict):
            for key in ("attributionSource", "lastAttributionSource"):
                b = contact.get(key)
                if isinstance(b, dict):
                    blocks.append(b)
    seen = set()
    for b in blocks:
        u = b.get("url")
        if not isinstance(u, str):
            continue
        s = u.strip()
        if not s.lower().startswith("http"):
            continue
        low = s.lower()
        if "quote/details/" not in low and "submission_id=" not in low and "/booking?" not in low:
            continue
        if s in seen:
            continue
        seen.add(s)
        return s
    return None


def _coerce_stringly_json_payload(payload):
    """
    GHL sometimes sends nested objects as JSON **strings** (customData, calendar, contact, body).
    Until parsed, `payload.get("calendar")` is not a dict and quote URL / appointmentId are invisible.
    """
    if not isinstance(payload, dict):
        return

    def _parse_obj_str(val):
        if not isinstance(val, str):
            return None
        s = val.strip()
        if not s.startswith("{"):
            return None
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    for key in (
        "customData",
        "custom_data",
        "calendar",
        "contact",
        "appointment",
        "booking",
        "body",
        "triggerData",
        "meta",
        "payload",
    ):
        v = payload.get(key)
        inner = _parse_obj_str(v)
        if inner is not None:
            payload[key] = inner

    cal = payload.get("calendar")
    if isinstance(cal, dict):
        for subk in ("contact", "appointment", "booking"):
            sv = cal.get(subk)
            inner = _parse_obj_str(sv)
            if inner is not None:
                cal[subk] = inner


def _derived_quote_total_from_submission(submission):
    """
    Effective quote total for Jobber when `submission.final_total` is still 0 (common before admin
    approval): sum selection line totals, then selected package quotes, then rollups / original total.
    """
    try:
        ft = float(submission.final_total)
        if ft > 0:
            return ft
    except (TypeError, ValueError):
        pass
    agg = submission.customerserviceselection_set.aggregate(s=Sum("final_total_price"))
    val = agg.get("s")
    if val is not None:
        try:
            f = float(val)
            if f > 0:
                return f
        except (TypeError, ValueError):
            pass
    total = Decimal("0")
    for sel in submission.customerserviceselection_set.filter(selected_package__isnull=False).only(
        "id", "selected_package_id"
    ):
        pq = (
            CustomerPackageQuote.objects.filter(
                service_selection_id=sel.id,
                package_id=sel.selected_package_id,
                is_selected=True,
            )
            .only("total_price", "admin_override_price")
            .first()
        )
        if pq is None:
            continue
        ep = pq.admin_override_price if pq.admin_override_price is not None else pq.total_price
        if ep is not None:
            total += ep
    if total > 0:
        return float(total)
    orig = getattr(submission, "original_final_total", None)
    if orig is not None:
        try:
            o = float(orig)
            if o > 0:
                return o
        except (TypeError, ValueError):
            pass
    try:
        roll = (
            float(submission.total_base_price or 0)
            + float(submission.total_adjustments or 0)
            + float(submission.total_surcharges or 0)
            + float(getattr(submission, "total_addons_price", None) or 0)
        )
        if roll > 0:
            return roll
    except (TypeError, ValueError):
        pass
    ad = submission.additional_data if isinstance(submission.additional_data, dict) else {}
    for key in (
        "final_total",
        "approved_price",
        "quote_total",
        "total_price",
        "grand_total",
        "quote_value",
        "total",
    ):
        f = _parse_priceish_number(ad.get(key))
        if f is not None:
            return f
    # In-person bids: no dollar amount until the visit — still create a scheduled Jobber job at $0.
    if getattr(submission, "is_bid_in_person", False):
        return 0.0
    return None


def _parse_priceish_number(val):
    """Parse GHL / form values like 525, '525.00', '$1,234.56' → positive float or None."""
    if val in (None, ""):
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            f = float(val)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None
    s = str(val).strip()
    if not s:
        return None
    for ch in ("$", "€", "£", ",", " ", "\u00a0"):
        s = s.replace(ch, "")
    try:
        f = float(s)
        return f if f > 0 else None
    except ValueError:
        return None


def _merged_ghl_quote_price(merged):
    """
    First positive price from GHL workflow payload.

    Custom Data keys like `Quote Value` + `{{contact.quote_value}}` only work when that merge tag
    resolves non-empty at send time — otherwise scan flat keys (408+) for quote-related fields.
    """
    if not isinstance(merged, dict):
        return None
    explicit_keys = (
        "Quote Value",
        "Quote value",
        "quote_value",
        "Total Price",
        "total_price",
        "final_total",
        "contact.quote_value",
        "contact.quoteValue",
        "approved_price",
        "Approved Price",
        "Quote Total",
        "quote_total",
        "Grand Total",
        "Invoice Total",
        "Total",
    )
    for k in explicit_keys:
        f = _parse_priceish_number(merged.get(k))
        if f is not None:
            return f
    lower_exact = {str(k).lower(): v for k, v in merged.items() if isinstance(k, str)}
    for lk in ("quote value", "total price", "quote_value", "approved price"):
        if lk in lower_exact:
            f = _parse_priceish_number(lower_exact[lk])
            if f is not None:
                return f
    for k, v in merged.items():
        if not isinstance(k, str):
            continue
        kl = k.replace("_", " ").lower()
        if "quote" not in kl:
            continue
        if not any(x in kl for x in ("value", "total", "price", "amount")):
            continue
        f = _parse_priceish_number(v)
        if f is not None:
            return f
    return None


def _normalize_flat_ghl_identity_into_merged(merged):
    """
    GHL workflow JSON often uses camelCase at the top level (firstName, lastName) with no nested
    `contact` object — without this, email/contact resolution and Jobber client fields stay empty.
    """
    if not isinstance(merged, dict):
        return
    if not (merged.get("first_name") or "").strip():
        fn = merged.get("firstName") or merged.get("First Name")
        if fn not in (None, ""):
            merged["first_name"] = str(fn).strip()
    if not (merged.get("last_name") or "").strip():
        ln = merged.get("lastName") or merged.get("Last Name")
        if ln not in (None, ""):
            merged["last_name"] = str(ln).strip()
    if not (merged.get("email") or "").strip():
        em = merged.get("Email") or merged.get("contact_email")
        if em not in (None, ""):
            merged["email"] = str(em).strip()
    if merged.get("phone") in (None, ""):
        ph = merged.get("phoneNumber") or merged.get("Phone") or merged.get("mobile")
        if ph not in (None, ""):
            merged["phone"] = str(ph).strip()


def _ghl_booking_failure_detail(submission, merged, payload, quote_url, cid_dbg):
    """Structured diagnostics for 400 responses (visible in GHL workflow execution)."""
    derived_db = _derived_quote_total_from_submission(submission) if submission is not None else None
    cal = payload.get("calendar") if isinstance(payload, dict) else None
    cal_ok = isinstance(cal, dict)
    appt = ""
    if cal_ok:
        appt = str(cal.get("appointmentId") or cal.get("id") or "").strip()
    m = merged if isinstance(merged, dict) else {}
    fn = (m.get("first_name") or m.get("firstName") or "").strip()
    ln = (m.get("last_name") or m.get("lastName") or "").strip()
    em = (m.get("email") or m.get("Email") or "").strip()
    ph = m.get("phone") or m.get("Phone") or m.get("phoneNumber")
    ph = str(ph).strip() if ph not in (None, "") else ""
    hints = []
    if submission is None:
        hints.append(
            "No CustomerSubmission: check quote URL in payload, contact_id vs submission.ghl_contact_id, "
            "or email match."
        )
    else:
        hints.append("Submission matched but Jobber booking payload could not be built.")
        try:
            ft = float(submission.final_total)
        except (TypeError, ValueError):
            ft = None
        bid_ip = getattr(submission, "is_bid_in_person", False)
        if (
            not bid_ip
            and (ft is None or ft <= 0)
            and (derived_db is None or derived_db <= 0)
        ):
            qp = _merged_ghl_quote_price(m)
            if qp is None or qp <= 0:
                hints.append(
                    "No positive price: submission.final_total is 0, no sum from service lines / "
                    "package quotes / rollups, and GHL Quote Value is empty — complete package pricing "
                    "on the quote or set Quote Value on the contact."
                )
        if bid_ip and (derived_db is None or derived_db <= 0):
            hints.append(
                "This submission is bid-in-person (is_bid_in_person=True): a $0 Jobber job is allowed "
                "after deploy; if you still see this error, check name/email/phone and package rows."
            )
        if not (fn and ln):
            hints.append("Missing first_name/last_name (add firstName/lastName or first_name/last_name to payload).")
        if not em and not ph:
            hints.append("Missing email and phone on webhook payload.")
    return {
        "failure_reason": "submission_not_resolved" if submission is None else "booking_payload_incomplete",
        "hints": hints,
        "extracted_contact_id": cid_dbg,
        "submission_id": str(submission.id) if submission is not None else None,
        "quote_url_detected": bool(quote_url),
        "calendar_present": cal_ok,
        "calendar_appointment_id": appt or None,
        "merged_has_first_last": bool(fn and ln),
        "merged_has_email_or_phone": bool(em or ph),
        "submission_final_total": float(submission.final_total) if submission is not None else None,
        "derived_total_from_db": derived_db,
        "merged_quote_value_raw": m.get("Quote Value"),
        "merged_ghl_price_parsed": _merged_ghl_quote_price(m),
        "payload_key_count": len(payload) if isinstance(payload, dict) else 0,
        "is_bid_in_person": getattr(submission, "is_bid_in_person", False) if submission is not None else False,
    }


def _merge_ghl_booking_payload_top_level(payload):
    """Merge customData into a flat dict for field lookup (quote URL, form keys)."""
    merged = _ghl_webhook_payload_merged(payload if isinstance(payload, dict) else {})
    cd = payload.get("customData") if isinstance(payload, dict) else None
    if isinstance(cd, dict):
        for k, v in cd.items():
            if k not in merged or merged.get(k) in ("", None):
                merged[k] = v
    return merged


def _merge_ghl_contact_profile_into_merged(payload, merged):
    """
    Copy standard fields + customFields from nested `contact` into `merged`.

    Workflow **Custom Data** merge tags (e.g. {{contact.quote_submission_url}}) often resolve to
    empty or stale values. The same booking payload usually still includes `contact` with
    `customFields` from the live CRM record — we read those so the quote URL is available even when
    the webhook action's customData failed to interpolate.
    """
    if not isinstance(merged, dict):
        return
    c = payload.get("contact") if isinstance(payload.get("contact"), dict) else None
    if not c:
        cal = payload.get("calendar") if isinstance(payload.get("calendar"), dict) else None
        if cal:
            c = cal.get("contact") if isinstance(cal.get("contact"), dict) else None
    if not c:
        appt = payload.get("appointment") if isinstance(payload.get("appointment"), dict) else None
        if appt:
            c = appt.get("contact") if isinstance(appt.get("contact"), dict) else None
    if not c:
        return

    def _fill(key, val):
        if val in (None, ""):
            return
        if key not in merged or merged.get(key) in ("", None):
            merged[key] = val

    _fill("first_name", c.get("firstName") or c.get("first_name"))
    _fill("last_name", c.get("lastName") or c.get("last_name"))
    _fill("email", c.get("email"))
    _fill("phone", c.get("phone") or c.get("phoneNumber") or c.get("mobile"))
    _fill("address1", c.get("address1"))
    _fill("city", c.get("city"))
    _fill("state", c.get("state"))
    _fill("postalCode", c.get("postalCode") or c.get("postal_code"))

    cfs = c.get("customFields")
    if not isinstance(cfs, list):
        return
    for item in cfs:
        if not isinstance(item, dict):
            continue
        val = item.get("value")
        if val in (None, ""):
            continue
        fk = str(item.get("fieldKey") or "").strip()
        name = str(item.get("name") or "").strip()
        if name:
            _fill(name, val)
        if fk:
            _fill(fk, val)
            if "." in fk:
                _fill(fk.split(".")[-1], val)


def _pick_preferred_submission(subs, label):
    """Prefer approved / packages_selected / submitted, then latest in list order."""
    if not subs:
        return None
    preferred = ("approved", "packages_selected", "submitted")
    for st in preferred:
        for s in subs:
            if getattr(s, "status", None) == st:
                logger.info(
                    "GHL booking: submission from %s picked submission=%s status=%s",
                    label,
                    s.id,
                    st,
                )
                return s
    s0 = subs[0]
    logger.info(
        "GHL booking: submission from %s picked latest submission=%s (no preferred status)",
        label,
        s0.id,
    )
    return s0


def _resolve_customer_submission_for_booking(payload, merged):
    """
    Resolve CustomerSubmission for this appointment:
      1) UUID extracted from quote / booking URL (attribution, workflow customData, merged fields).
      2) GHL contact id anywhere in payload → `ghl_contact_id` match.
      3) Email on merged payload → `customer_email__iexact` (calendar payloads sometimes omit contact id).
    """
    quote_url = _quote_submission_url_from_payload(payload) or _quote_submission_url_from_merged(merged)
    sub_uuid = _extract_submission_uuid_from_quote_url(quote_url)
    if sub_uuid:
        try:
            uid = uuid.UUID(str(sub_uuid))
        except ValueError:
            uid = None
        if uid:
            sub = (
                CustomerSubmission.objects.select_related("location", "size_range")
                .filter(id=uid)
                .first()
            )
            if sub:
                logger.info(
                    "GHL booking: submission from quote URL submission_id=%s url_present=%s",
                    sub.id,
                    bool(quote_url),
                )
                return sub

    cid = _extract_ghl_webhook_contact_id(payload)
    if cid:
        subs = list(
            CustomerSubmission.objects.select_related("location", "size_range")
            .filter(ghl_contact_id=str(cid))
            .order_by("-updated_at")[:25]
        )
        if subs:
            return _pick_preferred_submission(subs, f"ghl_contact_id={cid}")
        logger.warning(
            "GHL booking: no CustomerSubmission with ghl_contact_id=%s (sync contact from quote flow)",
            cid,
        )

    email = (merged.get("email") or "").strip()
    if email:
        subs = list(
            CustomerSubmission.objects.select_related("location", "size_range")
            .filter(customer_email__iexact=email)
            .order_by("-updated_at")[:25]
        )
        if subs:
            logger.info("GHL booking: resolving by customer_email=%s (contact id missing or no ghl link)", email)
            return _pick_preferred_submission(subs, f"email={email}")

    return None


def _quote_submission_url_from_payload(payload):
    """
    URL used to resolve CustomerSubmission for the booking.

    1) **attributionSource.url** (top-level + nested under `contact`) — GHL records the quote page
       URL for calendar bookings from an embedded widget (reliable).
    2) **customData** — workflow merge fields (often empty or stale vs the open tab).
    3) Other merged top-level contact fields as last resort.
    """
    if not isinstance(payload, dict):
        return None
    url = _quote_url_from_attribution(payload)
    if url:
        return url
    cd = payload.get("customData")
    url = _first_http_quote_url_from_dict(cd)
    if url:
        return url
    url = _http_quote_url_from_dict_values(cd)
    if url:
        return url
    merged_top = _ghl_webhook_payload_merged(payload)
    url = _first_http_quote_url_from_dict(merged_top)
    if url:
        return url
    url = _http_quote_url_from_dict_values(merged_top)
    if url:
        return url
    return None


def _quote_submission_url_from_merged(merged):
    """
    Quote / booking URL from the flat merged dict.

    GHL often sends hundreds of top-level custom field keys; the URL may appear under a known key
    or as any string value starting with http (same as _quote_submission_url_from_payload scan).
    """
    m = merged if isinstance(merged, dict) else {}
    url = _first_http_quote_url_from_dict(m)
    if url:
        return url
    return _http_quote_url_from_dict_values(m)


def _parse_multi_value_field(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    s = str(val).strip()
    if not s:
        return []
    for sep in (",", ";", "|"):
        if sep in s:
            return [x.strip() for x in s.split(sep) if x.strip()]
    return [s]


def _package_feature_description(package):
    if not package:
        return ""
    lines = []
    qs = package.package_features.select_related("feature").filter(is_included=True).order_by("feature__name")
    for pf in qs:
        nm = (pf.feature.name or "").strip()
        if nm:
            lines.append(nm)
    if lines:
        return "; ".join(lines)
    svc = getattr(package, "service", None)
    return (getattr(svc, "description", None) or "").strip()


def _job_detail_dict_from_submission_and_ghl(submission, merged):
    ad = submission.additional_data if isinstance(submission.additional_data, dict) else {}

    def pick(*keys):
        for k in keys:
            v = merged.get(k)
            if v not in (None, "", []):
                return v
        for k in keys:
            v = ad.get(k)
            if v not in (None, "", []):
                return v
        return None

    bedrooms = pick("# of Bedrooms to be Cleaned", "bedrooms", "Bedrooms")
    bathrooms = pick("# of Bathrooms to be Cleaned", "bathrooms", "Bathrooms")
    sqft = pick("House Size", "square_footage", "Square footage")
    if submission.size_range:
        sr = submission.size_range
        if not sqft:
            mn = getattr(sr, "min_sqft", None)
            mx = getattr(sr, "max_sqft", None)
            if mn is not None:
                if mx:
                    sqft = f"{mn}–{mx} sq ft"
                else:
                    sqft = f"{mn}+ sq ft"
    if submission.actual_sqft and not sqft:
        sqft = str(submission.actual_sqft)
    condition = pick(
        "Clutter Scale: Rate the Current Clutter Level of Residence",
        "Cleanliness Scale: Rate the Current Cleanliness Level of Residence",
        "condition",
    )
    pets = pick("Special Details (Which apply)", "pets", "Pets")
    add_ons = pick("Additional Services", "add_ons")
    if submission.submission_addons.exists():
        addon_bits = [
            f"{a.addon.name} x{a.quantity}"
            for a in submission.submission_addons.select_related("addon").all()
        ]
        if addon_bits:
            existing = (add_ons or "").strip()
            merged_addons = "; ".join(addon_bits)
            add_ons = f"{existing}; {merged_addons}".strip("; ") if existing else merged_addons
    special = pick(
        "Notes",
        "Please include any additional information or questions you may have.",
        "special_instructions",
    )
    entry = pick("Entry instructions", "entry_instructions")

    out = {
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "square_footage": sqft,
        "condition": condition,
        "pets": pets,
        "add_ons": add_ons,
        "special_instructions": special,
        "entry_instructions": entry,
    }
    pfloat = _derived_quote_total_from_submission(submission)
    service_guess = (pick("Type of Service") or "") or ""
    if not service_guess and submission.customerserviceselection_set.exists():
        service_guess = submission.customerserviceselection_set.select_related("service").first().service.name
    if pfloat and pfloat > 0:
        low, high, _slot = _compute_labor_and_slot(pfloat, service_type=service_guess, team_size=2)
        if low is not None and high is not None:
            out["estimated_labor_hours"] = f"{low}–{high} (team slot from booking rules)"
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _booking_confirm_dict_from_submission(submission, merged, calendar_obj):
    """
    Build execute_booking_confirm() input from CustomerSubmission + GHL workflow fields.
    Contact/address: prefer GHL webhook (post-booking) then submission.
    """
    m = merged
    first_name = (m.get("first_name") or submission.first_name or "").strip()
    last_name = (m.get("last_name") or submission.last_name or "").strip()
    email = (m.get("email") or submission.customer_email or "").strip() or None
    phone_raw = m.get("phone") if m.get("phone") not in (None, "") else submission.customer_phone
    phone = str(phone_raw).strip() if phone_raw else None

    street1 = (submission.street_address or m.get("address1") or m.get("full_address") or "").strip()
    city = ""
    if submission.location_id:
        loc = submission.location
        city = (loc.name or "").strip()
    if not city:
        city = (m.get("city") or "").strip()
    if not city:
        city = (config("JOBBER_DEFAULT_SERVICE_CITY", default="") or "").strip()
    province = (config("JOBBER_DEFAULT_SERVICE_PROVINCE", default="QC") or "QC").strip()
    postal_code = (submission.postal_code or m.get("postalCode") or m.get("postal_code") or "").strip()
    fallback_pc = (config("JOBBER_FALLBACK_POSTAL_CODE", default="") or "").strip()
    if not postal_code and fallback_pc:
        postal_code = fallback_pc

    start_iso = None
    if isinstance(calendar_obj, dict):
        start_iso = (calendar_obj.get("startTime") or calendar_obj.get("start_time") or "").strip() or None
    if not start_iso:
        start_iso = (m.get("scheduled_start_iso") or "").strip() or None

    selections = list(
        submission.customerserviceselection_set.select_related("service", "selected_package").prefetch_related(
            "selected_package__package_features__feature"
        ).all()
    )
    services_rows = []
    for sel in selections:
        pkg = sel.selected_package
        if not pkg:
            continue
        desc = _package_feature_description(pkg)
        try:
            line_price = float(sel.final_total_price)
        except (TypeError, ValueError):
            line_price = 0.0
        if line_price <= 0:
            pq = (
                CustomerPackageQuote.objects.filter(
                    service_selection_id=sel.id,
                    package_id=pkg.id,
                    is_selected=True,
                )
                .only("total_price", "admin_override_price")
                .first()
            )
            if pq is not None:
                ep = pq.admin_override_price if pq.admin_override_price is not None else pq.total_price
                if ep is not None:
                    try:
                        line_price = float(ep)
                    except (TypeError, ValueError):
                        line_price = 0.0
        if line_price <= 0:
            if not getattr(submission, "is_bid_in_person", False):
                continue
            line_price = 0.0
        services_rows.append(
            {
                "service_type": sel.service.name,
                "package_title": pkg.name,
                "package_description": desc,
                "line_item_price": line_price,
            }
        )

    if not services_rows:
        types = [s.service.name for s in selections if s.service_id]
        pkg_name = ""
        if selections:
            sp = selections[0].selected_package
            pkg_name = sp.name if sp else ""
        sub_total = _derived_quote_total_from_submission(submission)
        bid_ip = getattr(submission, "is_bid_in_person", False)
        if types and sub_total is not None and (sub_total > 0 or bid_ip):
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "street1": street1,
                "city": city,
                "province": province,
                "postal_code": postal_code,
                "scheduled_start_iso": start_iso,
                "service_types": types,
                "package_title": pkg_name or "Approved services",
                "package_description": "",
                "approved_price": float(sub_total),
            }
            data.update(_job_detail_dict_from_submission_and_ghl(submission, m))
            return data
        ghl_price = _merged_ghl_quote_price(m)
        price_for_job = None
        if sub_total is not None and (sub_total > 0 or bid_ip):
            price_for_job = float(sub_total)
        if price_for_job is None and ghl_price is not None and ghl_price > 0:
            price_for_job = ghl_price
        if (
            first_name
            and last_name
            and (email or phone)
            and price_for_job is not None
            and (price_for_job > 0 or bid_ip)
        ):
            svc = (types[0] if types else None) or (
                "Bid in person (price TBD)" if bid_ip else "Cleaning service"
            )
            data = {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "street1": street1,
                "city": city,
                "province": province,
                "postal_code": postal_code,
                "scheduled_start_iso": start_iso,
                "service_type": svc,
                "package_title": (pkg_name or "Bid in person — price TBD")
                if bid_ip
                else (pkg_name or "Approved quote"),
                "package_description": "",
                "approved_price": price_for_job,
            }
            data.update(_job_detail_dict_from_submission_and_ghl(submission, m))
            logger.info(
                "GHL booking: fallback single line price=%s (submission.final_total=%s ghl_quote=%s) submission=%s",
                price_for_job,
                sub_total,
                ghl_price,
                submission.id,
            )
            return data
        return None

    if len(services_rows) == 1:
        row = services_rows[0]
        data = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
            "street1": street1,
            "city": city,
            "province": province,
            "postal_code": postal_code,
            "scheduled_start_iso": start_iso,
            "service_type": row["service_type"],
            "package_title": row["package_title"],
            "package_description": row["package_description"],
            "approved_price": row["line_item_price"],
        }
        data.update(_job_detail_dict_from_submission_and_ghl(submission, m))
        return data

    data = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "street1": street1,
        "city": city,
        "province": province,
        "postal_code": postal_code,
        "scheduled_start_iso": start_iso,
        "services": services_rows,
    }
    data.update(_job_detail_dict_from_submission_and_ghl(submission, m))
    return data


def _booking_confirm_dict_from_ghl_only(merged, calendar_obj):
    """Fallback when no CustomerSubmission is found: map GHL custom fields only."""
    first_name = (merged.get("first_name") or "").strip()
    last_name = (merged.get("last_name") or "").strip()
    email = (merged.get("email") or "").strip() or None
    phone = merged.get("phone")
    if phone is not None:
        phone = str(phone).strip() or None
    street1 = (merged.get("address1") or merged.get("full_address") or "").strip()
    city = (merged.get("city") or "").strip()
    province = (
        merged.get("state")
        or merged.get("province")
        or config("JOBBER_DEFAULT_SERVICE_PROVINCE", default="QC")
        or "QC"
    ).strip()
    postal_code = (merged.get("postalCode") or merged.get("postal_code") or "").strip()
    fallback_pc = (config("JOBBER_FALLBACK_POSTAL_CODE", default="") or "").strip()
    if not postal_code and fallback_pc:
        postal_code = fallback_pc

    start_iso = None
    if isinstance(calendar_obj, dict):
        start_iso = (calendar_obj.get("startTime") or "").strip() or None

    types = _parse_multi_value_field(merged.get("Selected Services"))
    if not types:
        ts = (merged.get("Type of Service") or "").strip()
        if ts:
            types = [ts]
    if not types:
        types = ["Cleaning Service"]

    price_f = _merged_ghl_quote_price(merged)
    if price_f is None or price_f <= 0:
        return None

    pkg = (merged.get("Which Cleaning Package") or merged.get("package_title") or "Package").strip()
    desc = (merged.get("Quoted Services") or merged.get("package_description") or "").strip()

    data = {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "phone": phone,
        "street1": street1,
        "city": city,
        "province": province,
        "postal_code": postal_code,
        "scheduled_start_iso": start_iso,
        "service_types": types,
        "package_title": pkg,
        "package_description": desc,
        "approved_price": price_f,
        "bedrooms": merged.get("# of Bedrooms to be Cleaned"),
        "bathrooms": merged.get("# of Bathrooms to be Cleaned"),
        "square_footage": merged.get("House Size"),
        "condition": merged.get("Clutter Scale: Rate the Current Clutter Level of Residence"),
        "pets": merged.get("Special Details (Which apply)"),
        "add_ons": merged.get("Additional Services"),
        "special_instructions": merged.get("Notes")
        or merged.get("Please include any additional information or questions you may have."),
    }
    low, high, _ = _compute_labor_and_slot(price_f, service_type=types[0] if types else "", team_size=2)
    if low is not None and high is not None:
        data["estimated_labor_hours"] = f"{low}–{high}"
    return data


def _can_run_ghl_booking_webhook(request):
    expected = config("GHL_BOOKING_WEBHOOK_SECRET", default="").strip()
    if not expected:
        return True
    got = (request.headers.get("X-GHL-Booking-Webhook-Secret") or "").strip()
    return got == expected


class BookingSlotInfoView(APIView):
    """
    GET /api/jobber/booking/slot-info/?price=525&service_type=Residential First Clean&team_size=2
    Returns labor hours (low/high) and calendar slot duration for the given price and service type.
    Formulas: Residential First Clean -> price/65, price/55; Move-In/Out -> price/75, price/65.
    Slot duration = labor_high ÷ team_size, rounded to nearest 0.5 hour.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        price = request.query_params.get("price")
        service_type = (request.query_params.get("service_type") or "").strip()
        team_size = request.query_params.get("team_size", "2")
        if price is None:
            return Response(
                {"error": "Query param 'price' is required (approved quote total)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            p = float(price)
        except (TypeError, ValueError):
            return Response(
                {"error": "price must be a number"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if p <= 0:
            return Response(
                {"error": "price must be greater than 0"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        labor_low, labor_high, slot_duration = _compute_labor_and_slot(
            price=p, service_type=service_type or None, team_size=team_size
        )
        if labor_low is None:
            return Response(
                {"error": "Could not compute labor and slot"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "labor_hours_low": labor_low,
            "labor_hours_high": labor_high,
            "slot_duration_hours": slot_duration,
            "price": p,
            "service_type": service_type or None,
            "team_size": max(1, min(10, int(team_size) if str(team_size).strip().isdigit() else 2)),
        })


class BookingConfirmView(APIView):
    """
    POST /api/jobber/booking/confirm/
    Unified booking confirmation: find or create client → resolve or create property → create job in Jobber.

    Request body (from Pricing Calculator):
      Client: first_name, last_name, email, phone (at least one of email/phone).
      Address: street1 (or service_address), city, province, postal_code; optional street2.
      Service (choose one shape):
        - Legacy single: service_type (job title), package_title, package_description, approved_price.
        - Multiple labels: service_types (string array), package_title, package_description, approved_price
          (total is split evenly across line items).
        - Structured: services (array of { service_type, package_title?, package_description?, line_item_price | price }).
      Optional add_ons.
      Job details: bedrooms, bathrooms, square_footage, condition, pets, special_instructions, entry_instructions; optional estimated_labor_hours.
      Booking: scheduled_start_iso (ISO 8601) OR selected_date + selected_time.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        payload = _booking_confirm_payload_dict(request.data)
        result, err_resp = execute_booking_confirm(payload)
        if err_resp is not None:
            return err_resp
        return Response(result, status=status.HTTP_201_CREATED)


class GhlBookingConfirmedWebhookView(APIView):
    """
    POST — GoHighLevel workflow webhook after a contact books (e.g. “Customer Booked Appointment”).

    Expects the standard workflow JSON (contact fields, `calendar` with startTime / appointmentId,
    optional workflow `customData`).

    **Why `{{contact.quote_submission_url}}` in Custom Data is flaky:** that merge tag is
    re-evaluated when the HTTP action runs. It can be blank, lagging, or wrong compared to what you
    see on the contact record in the UI. The payload still usually includes `contact` with
    `customFields`; we merge those into the same lookup dict and also fall back to
    `contact.id` → `CustomerSubmission.ghl_contact_id`.

    URL resolution order: attribution **page** URL (quote/details), workflow customData, merged
    contact custom fields, then other merged keys.

    Auth (recommended): set GHL_BOOKING_WEBHOOK_SECRET and send header X-GHL-Booking-Webhook-Secret.

    Idempotency: same `calendar.appointmentId` only creates one Jobber job (stored in DB).
    """

    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_booking_webhook(request):
            logger.warning("GHL booking webhook forbidden: missing/invalid secret header")
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        payload = _parse_webhook_json_payload(request)
        merged = _merge_ghl_booking_payload_top_level(payload)
        _merge_ghl_contact_profile_into_merged(payload, merged)
        _normalize_flat_ghl_identity_into_merged(merged)
        cal = payload.get("calendar") if isinstance(payload.get("calendar"), dict) else {}

        appt_id = ""
        if isinstance(cal, dict):
            appt_id = str(cal.get("appointmentId") or cal.get("id") or "").strip()
        if appt_id:
            existing = GhlAppointmentJobberJobMap.objects.filter(ghl_appointment_id=appt_id).first()
            if existing:
                return Response(
                    {
                        "received": True,
                        "duplicate": True,
                        "ghl_appointment_id": appt_id,
                        "jobber_job_id": existing.jobber_job_id,
                    },
                    status=status.HTTP_200_OK,
                )

        submission = _resolve_customer_submission_for_booking(payload, merged)
        quote_url_dbg = _quote_submission_url_from_payload(payload) or _quote_submission_url_from_merged(merged)

        if submission is not None:
            booking_data = _booking_confirm_dict_from_submission(submission, merged, cal)
        else:
            booking_data = _booking_confirm_dict_from_ghl_only(merged, cal)

        if not booking_data:
            cid_dbg = _extract_ghl_webhook_contact_id(payload)
            detail = _ghl_booking_failure_detail(submission, merged, payload, quote_url_dbg, cid_dbg)
            logger.warning(
                "GHL booking webhook: could not build booking_data. contact_id=%s submission_found=%s "
                "email_in_merged=%s failure_reason=%s keys_sample=%s",
                cid_dbg,
                submission is not None,
                bool((merged.get("email") or "").strip()) if isinstance(merged, dict) else False,
                detail.get("failure_reason"),
                sorted(merged.keys())[:50] if isinstance(merged, dict) else [],
            )
            return Response(
                {
                    "error": "Could not build booking. See failure_reason, hints, and diagnostics.",
                    **detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        result, err_resp = execute_booking_confirm(booking_data)
        if err_resp is not None:
            return err_resp

        job = (result or {}).get("job") or {}
        jobber_id = job.get("id")
        if appt_id and jobber_id:
            sid = submission.id if submission is not None else None
            time_defaults = _ghl_calendar_map_defaults_from_cal(cal)
            GhlAppointmentJobberJobMap.objects.update_or_create(
                ghl_appointment_id=appt_id,
                defaults={
                    "jobber_job_id": str(jobber_id),
                    "submission_id": sid,
                    **time_defaults,
                },
            )

        return Response({"received": True, **(result or {})}, status=status.HTTP_201_CREATED)


def _ghl_booking_debug_shallow_dict(obj, max_keys=60, value_max_len=180):
    """Summarize a dict for debug JSON (avoid huge responses)."""
    if not isinstance(obj, dict):
        return {"_type": type(obj).__name__}
    out = {}
    for k in sorted(obj.keys())[:max_keys]:
        v = obj[k]
        if isinstance(v, dict):
            out[k] = f"<dict {len(v)} keys>"
        elif isinstance(v, list):
            out[k] = f"<list len={len(v)}>"
        else:
            s = "" if v is None else str(v)
            if len(s) > value_max_len:
                s = s[:value_max_len] + "…"
            out[k] = s
    if len(obj) > max_keys:
        out["_truncated"] = True
    return out


class GhlBookingWebhookDebugView(APIView):
    """
    POST — **Diagnostics only** (creates no Jobber job, writes no map row).

    Same auth as `GhlBookingConfirmedWebhookView` (`GHL_BOOKING_WEBHOOK_SECRET` +
    `X-GHL-Booking-Webhook-Secret` when secret is configured).

    Temporarily set your GHL workflow webhook URL to this path, run one booking, inspect the JSON
    response. Compare `raw_body_preview` and `content_type` to what webhook.site shows — if GHL posts
    form-encoded data or a different JSON shape to your server, it will show up here.

    Path (under your API prefix): `.../webhooks/ghl/booking-confirmed/debug/`
    """

    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_booking_webhook(request):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        raw = getattr(request, "body", b"") or b""
        ct_full = request.META.get("CONTENT_TYPE") or ""
        ct = ct_full.split(";")[0].strip()

        parse_note = None
        if raw:
            try:
                text = raw.decode("utf-8")
                text = text.lstrip("\ufeff").strip()
                if not text.startswith("{"):
                    parse_note = "raw_body does not start with '{' — often form-encoded or HTML, not JSON"
            except UnicodeDecodeError as e:
                parse_note = f"utf8_decode_error: {e}"

        payload = _parse_webhook_json_payload(request)
        merged = _merge_ghl_booking_payload_top_level(payload)
        _merge_ghl_contact_profile_into_merged(payload, merged)
        _normalize_flat_ghl_identity_into_merged(merged)
        cal = payload.get("calendar") if isinstance(payload.get("calendar"), dict) else {}

        quote_url = _quote_submission_url_from_payload(payload) or _quote_submission_url_from_merged(merged)
        sub_uuid = _extract_submission_uuid_from_quote_url(quote_url)
        cid = _extract_ghl_webhook_contact_id(payload)
        submission = _resolve_customer_submission_for_booking(payload, merged)
        if submission is not None:
            booking_data = _booking_confirm_dict_from_submission(submission, merged, cal)
        else:
            booking_data = _booking_confirm_dict_from_ghl_only(merged, cal)

        cd = payload.get("customData")
        cd_out = None
        if isinstance(cd, dict):
            cd_out = _ghl_booking_debug_shallow_dict(cd, max_keys=40, value_max_len=500)
        elif cd is not None:
            cd_out = str(cd)[:500]

        preview_len = int(config("GHL_BOOKING_WEBHOOK_DEBUG_BODY_CHARS", default="6000"))
        preview_len = max(500, min(preview_len, 50000))
        raw_preview = raw.decode("utf-8", errors="replace")[:preview_len]

        def _type_name(x):
            return type(x).__name__ if x is not None else "null"

        return Response(
            {
                "debug": True,
                "content_type": ct,
                "content_type_full": ct_full[:200],
                "raw_body_bytes": len(raw),
                "raw_body_preview": raw_preview,
                "parse_hint": parse_note,
                "payload_key_count": len(payload) if isinstance(payload, dict) else 0,
                "calendar_type_after_parse": _type_name(payload.get("calendar")),
                "customData_type_after_parse": _type_name(payload.get("customData")),
                "payload_top_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
                "customData": cd_out,
                "calendar_keys": sorted(cal.keys()) if isinstance(cal, dict) else None,
                "extracted_contact_id": cid,
                "quote_url": (quote_url[:800] + "…") if quote_url and len(quote_url) > 800 else quote_url,
                "extracted_submission_uuid": sub_uuid,
                "submission_id": str(submission.id) if submission else None,
                "submission_status": getattr(submission, "status", None) if submission else None,
                "booking_data_ok": bool(booking_data),
                "merged_fields": _ghl_booking_debug_shallow_dict(merged, max_keys=80, value_max_len=160),
            },
            status=status.HTTP_200_OK,
        )


def _can_run_ghl_calendar_sync(request):
    """Allow sync if X-GHL-Calendar-Sync-Secret matches env, or authenticated admin user."""
    expected = config("GHL_CALENDAR_SYNC_SECRET", default="").strip()
    if expected:
        got = (request.headers.get("X-GHL-Calendar-Sync-Secret") or "").strip()
        if got == expected:
            return True
    user = getattr(request, "user", None)
    if user and user.is_authenticated and getattr(user, "is_admin", False):
        return True
    return False


class GhlCalendarSyncFromJobberView(APIView):
    """
    POST — Pull Jobber visits for a time window and upsert GoHighLevel calendar **block slots**
    so the embedded booking calendar reflects Jobber busy times.

    Auth: set GHL_CALENDAR_SYNC_SECRET in env and send header X-GHL-Calendar-Sync-Secret,
    **or** call as an authenticated admin (is_admin).

    Body/query (optional):
      - after: ISO 8601 start of range (default: now UTC)
      - before: ISO 8601 end of range (default: now + 30 days UTC)

    Requires env: GHL_LOCATION_ID, GHL_BOOKING_CALENDAR_ID.

    GHL auth: set GHL_PRIVATE_INTEGRATION_TOKEN (or GHL_PIT) for Sub-Account Private Integration
    calendar access, **or** store OAuth in GHLAuthCredentials via /api/accounts/auth/connect/.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_calendar_sync(request):
            return Response(
                {"error": "Forbidden. Provide X-GHL-Calendar-Sync-Secret or authenticate as admin."},
                status=status.HTTP_403_FORBIDDEN,
            )

        after = (request.data.get("after") or request.query_params.get("after") or "").strip()
        before = (request.data.get("before") or request.query_params.get("before") or "").strip()
        if not after:
            after = timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        if not before:
            before = (timezone.now() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        result = sync_jobber_visits_to_ghl_blocks(after, before)
        return Response(result, status=status.HTTP_200_OK)


def _can_run_jobber_webhook(request):
    """
    Allow webhook if X-Jobber-Webhook-Secret matches JOBBER_WEBHOOK_SECRET.
    If secret is not configured, accept all requests (for quick local setup).
    """
    expected = config("JOBBER_WEBHOOK_SECRET", default="").strip()
    if not expected:
        return True
    got = (request.headers.get("X-Jobber-Webhook-Secret") or "").strip()
    return got == expected


def _parse_webhook_json_payload(request):
    """
    Raw JSON body → dict (preferred). Falls back to DRF parsed data.

    Prefer `request.body` so nested `contact`, `calendar`, and `customData` are preserved.
    Using `request.data.dict()` first can flatten / stringify nested JSON and strip workflow fields.
    """
    payload = {}
    raw = getattr(request, "body", b"") or b""
    if raw:
        try:
            text = raw.decode("utf-8")
            text = text.lstrip("\ufeff").strip()
            if text.startswith("{"):
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    payload = parsed
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            pass
    if not payload and hasattr(request, "data") and request.data is not None:
        rd = request.data
        try:
            if isinstance(rd, dict):
                payload = dict(rd)
            elif hasattr(rd, "dict"):
                payload = dict(rd.dict())
            else:
                payload = dict(rd)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    _coerce_stringly_json_payload(payload)
    return payload


def _extract_jobber_webhook_fields(payload):
    """Extract topic/item id from multiple possible webhook payload shapes."""
    if not isinstance(payload, dict):
        return "", None

    # Flatten common nested shapes:
    # - {"data": {"webHookEvent": {...}}} (Jobber)
    # - {"data": {...}}
    # - {"payload": {...}}
    nested = payload.get("data") if isinstance(payload.get("data"), dict) else None
    if not nested and isinstance(payload.get("payload"), dict):
        nested = payload.get("payload")
    source = nested or payload
    if isinstance(source.get("webHookEvent"), dict):
        source = source.get("webHookEvent")

    # Case-insensitive lookup
    norm = {str(k).lower(): v for k, v in source.items()}
    topic = str(
        norm.get("topic")
        or norm.get("event")
        or norm.get("type")
        or ""
    ).strip()
    item_id = (
        norm.get("itemid")
        or norm.get("item_id")
        or norm.get("resourceid")
        or norm.get("resource_id")
        or norm.get("id")
    )
    return topic, item_id


class JobberWebhookView(APIView):
    """
    POST — Receive Jobber webhook events.
    Core behavior:
      - CLIENT_CREATE / CLIENT_UPDATE: sync client tags → GHL contact tags
      - VISIT_CREATE / VISIT_UPDATE: sync that visit to GHL block slots
      - VISIT_DESTROY: delete mapped GHL block slot
      - JOB_CREATE: sync that job's visits to GHL block slots (fallback)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_jobber_webhook(request):
            logger.warning("Jobber webhook forbidden: missing/invalid secret header")
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        payload = _parse_webhook_json_payload(request)
        topic, item_id = _extract_jobber_webhook_fields(payload)
        logger.warning(
            "Jobber webhook received: content_type=%s payload_keys=%s parsed_topic=%s parsed_item_id=%s",
            request.content_type,
            sorted(list(payload.keys())) if isinstance(payload, dict) else [],
            topic,
            str(item_id) if item_id is not None else None,
        )
        print(
            "[Jobber webhook] received content_type=%s keys=%s topic=%s item_id=%s"
            % (
                request.content_type,
                sorted(list(payload.keys())) if isinstance(payload, dict) else [],
                topic,
                str(item_id) if item_id is not None else None,
            )
        )

        if topic not in (
            "CLIENT_CREATE",
            "CLIENT_UPDATE",
            "VISIT_CREATE",
            "VISIT_UPDATE",
            "VISIT_DESTROY",
            "JOB_CREATE",
        ):
            logger.warning("Jobber webhook ignored: unsupported topic=%s payload=%s", topic, payload)
            print("[Jobber webhook] ignored topic=%s payload=%s" % (topic, payload))
            return Response(
                {"received": True, "ignored": True, "reason": f"Unsupported topic: {topic or 'unknown'}"},
                status=status.HTTP_200_OK,
            )
        if not item_id:
            logger.warning("Jobber webhook invalid: missing item id for topic=%s payload=%s", topic, payload)
            return Response({"error": f"Missing itemId for {topic} webhook"}, status=status.HTTP_400_BAD_REQUEST)

        if topic in ("CLIENT_CREATE", "CLIENT_UPDATE"):
            result = sync_jobber_client_tags_to_ghl(str(item_id))
            logger.warning("Jobber webhook tag_sync result: topic=%s item_id=%s result=%s", topic, item_id, result)
            print("[Jobber webhook] tag_sync topic=%s item_id=%s result=%s" % (topic, item_id, result))
            return Response(
                {"received": True, "topic": topic, "itemId": str(item_id), "tag_sync": result},
                status=status.HTTP_200_OK,
            )

        if topic in ("VISIT_CREATE", "VISIT_UPDATE"):
            result = sync_jobber_visit_to_ghl_blocks(str(item_id))
        elif topic == "VISIT_DESTROY":
            result = delete_jobber_visit_from_ghl_blocks(str(item_id))
        else:
            result = sync_jobber_job_to_ghl_blocks(str(item_id))
        logger.warning("Jobber webhook sync result: topic=%s item_id=%s result=%s", topic, item_id, result)
        print("[Jobber webhook] sync topic=%s item_id=%s result=%s" % (topic, item_id, result))
        return Response(
            {"received": True, "topic": topic, "itemId": str(item_id), "sync": result},
            status=status.HTTP_200_OK,
        )


def _can_run_ghl_tag_sync_webhook(request):
    """Optional secret for inbound GHL → Jobber tag webhooks."""
    expected = config("GHL_TAG_SYNC_WEBHOOK_SECRET", default="").strip()
    if not expected:
        return True
    got = (request.headers.get("X-GHL-Tag-Sync-Secret") or "").strip()
    return got == expected


def _can_run_ghl_note_sync_webhook(request):
    """
    Optional secret for GHL → Jobber note forwarding.
    Uses GHL_NOTE_SYNC_WEBHOOK_SECRET + X-GHL-Note-Sync-Secret, or falls back to tag sync secret/header.
    """
    note_sec = config("GHL_NOTE_SYNC_WEBHOOK_SECRET", default="").strip()
    tag_sec = config("GHL_TAG_SYNC_WEBHOOK_SECRET", default="").strip()
    expected = note_sec or tag_sec
    if not expected:
        return True
    got_note = (request.headers.get("X-GHL-Note-Sync-Secret") or "").strip()
    got_tag = (request.headers.get("X-GHL-Tag-Sync-Secret") or "").strip()
    return got_note == expected or got_tag == expected


def _extract_ghl_note_create_fields(data):
    """
    Parse GHL NoteCreate webhook / workflow payload.
    See: https://marketplace.gohighlevel.com/docs/webhook/NoteCreate
    """
    merged = _ghl_webhook_payload_merged(data if isinstance(data, dict) else {})
    contact_id = merged.get("contactId") or merged.get("contact_id")
    note_id = merged.get("id") or merged.get("noteId") or merged.get("note_id")
    body = merged.get("body")
    c = merged.get("contact")
    if isinstance(c, dict):
        contact_id = contact_id or c.get("id") or c.get("contactId")
    lowered = {str(k).lower(): v for k, v in merged.items()}
    if not contact_id:
        contact_id = lowered.get("contactid") or lowered.get("contact_id")
    if not note_id:
        note_id = lowered.get("noteid") or lowered.get("note_id")
    if body is None:
        body = merged.get("note") or merged.get("message") or merged.get("text")
    if contact_id is not None:
        contact_id = str(contact_id).strip()
    if note_id is not None:
        note_id = str(note_id).strip()
    return contact_id or None, note_id or None, body


def _normalize_optional_note_id(note_id):
    s = str(note_id or "").strip()
    if s.lower() in ("", "none", "null", "undefined", "nan"):
        return ""
    return s


def _ghl_webhook_payload_merged(data):
    """Flatten top-level + optional `body` object from GHL HTTP actions."""
    if not isinstance(data, dict):
        return {}
    merged = dict(data)
    body = data.get("body")
    if isinstance(body, dict):
        merged.update(body)
    return merged


def _coerce_ghl_id(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _contact_id_candidates_from_dict(d):
    if not isinstance(d, dict):
        return []
    out = []
    c = d.get("contact")
    if isinstance(c, dict):
        for k in ("id", "contactId", "_id", "contact_id"):
            v = _coerce_ghl_id(c.get(k))
            if v:
                out.append(v)
    for k in (
        "contactId",
        "contact_id",
        "ContactId",
        "customerId",
        "customer_id",
        "crmContactId",
    ):
        v = _coerce_ghl_id(d.get(k))
        if v:
            out.append(v)
    for k in ("client", "customer", "attendee", "bookedBy"):
        blk = d.get(k)
        if isinstance(blk, dict):
            v = _coerce_ghl_id(blk.get("id") or blk.get("contactId") or blk.get("customerId"))
            if v:
                out.append(v)
    return out


def _extract_ghl_webhook_contact_id(data):
    """
    Resolve contact id from GHL workflow / webhook JSON (nested shapes, body wrapper, common keys).

    Calendar appointment payloads often nest `contactId` under `calendar` / `appointment` only —
    not at the top level.
    """
    if not isinstance(data, dict):
        return None
    merged = _ghl_webhook_payload_merged(data)
    candidates = []
    if merged:
        candidates.extend(_contact_id_candidates_from_dict(merged))

    for blk in (
        data.get("calendar"),
        data.get("appointment"),
        data.get("booking"),
        data.get("meta"),
        data.get("payload"),
        data.get("event"),
    ):
        if isinstance(blk, dict):
            candidates.extend(_contact_id_candidates_from_dict(blk))
            nested = blk.get("appointment")
            if isinstance(nested, dict):
                candidates.extend(_contact_id_candidates_from_dict(nested))

    cal = data.get("calendar")
    if isinstance(cal, dict):
        ap = cal.get("appointment")
        if isinstance(ap, dict):
            candidates.extend(_contact_id_candidates_from_dict(ap))

    for cid in candidates:
        if cid:
            return cid

    if not merged:
        return None
    lowered = {str(k).lower(): v for k, v in merged.items()}
    return _coerce_ghl_id(lowered.get("contactid") or lowered.get("contact_id"))


def _extract_ghl_webhook_tags(data):
    """Optional tag list from payload; must be a list of strings or mixed (normalized upstream)."""
    merged = _ghl_webhook_payload_merged(data)
    tags = merged.get("tags")
    if tags is None:
        c = merged.get("contact")
        if isinstance(c, dict):
            tags = c.get("tags")
    return tags if isinstance(tags, list) else None


class GhlContactTagsWebhookView(APIView):
    """
    POST — Inbound webhook when GHL contact tags change (configure in GHL workflow / HTTP action).

    Auth: set GHL_TAG_SYNC_WEBHOOK_SECRET and send header X-GHL-Tag-Sync-Secret (recommended).

    Body (JSON), flexible shapes:
      - { "contactId": "...", "tags": ["a", "b"] }
      - { "contact_id": "...", "tags": [...] }
      - { "contact": { "id": "...", "tags": [...] } }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_tag_sync_webhook(request):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        data = _parse_webhook_json_payload(request)
        contact_id = _extract_ghl_webhook_contact_id(data)
        tags = _extract_ghl_webhook_tags(data)
        if not contact_id:
            logger.warning(
                "GHL contact-tags webhook missing contactId; keys=%s",
                sorted(data.keys()) if isinstance(data, dict) else [],
            )
            return Response({"error": "contactId required"}, status=status.HTTP_400_BAD_REQUEST)

        result = sync_ghl_contact_tags_to_jobber(str(contact_id), tag_names_from_payload=tags)
        status_code = status.HTTP_200_OK if result.get("ok") or result.get("skipped") else status.HTTP_502_BAD_GATEWAY
        if status_code != status.HTTP_200_OK:
            logger.warning(
                "GHL contact-tags webhook sync failed contactId=%s error=%s",
                contact_id,
                result.get("error"),
            )
        return Response({"received": True, "contactId": str(contact_id), "tag_sync": result}, status=status_code)


class GhlContactNoteWebhookView(APIView):
    """
    POST — Forward one GHL CRM contact note to Jobber client notes (internal notes area).

    Configure a GHL workflow on note created (or send native NoteCreate webhook shape):
      { "type": "NoteCreate", "contactId": "...", "id": "<note id>", "body": "..." }

    Auth: GHL_NOTE_SYNC_WEBHOOK_SECRET + X-GHL-Note-Sync-Secret, or reuse tag sync secret/header.
    If body is omitted, the server loads the note via GET /notes/:id.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_note_sync_webhook(request):
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        data = _parse_webhook_json_payload(request)
        contact_id, note_id, body = _extract_ghl_note_create_fields(data)
        if not contact_id:
            logger.warning(
                "GHL note webhook missing contactId; keys=%s",
                sorted(data.keys()) if isinstance(data, dict) else [],
            )
            return Response(
                {"error": "contactId required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        safe_note_id = _normalize_optional_note_id(note_id)
        result = sync_ghl_note_to_jobber(
            ghl_contact_id=str(contact_id),
            ghl_note_id=safe_note_id,
            note_body=body,
        )
        status_code = status.HTTP_200_OK if result.get("ok") else status.HTTP_502_BAD_GATEWAY
        if status_code != status.HTTP_200_OK:
            logger.warning(
                "GHL note forward failed contactId=%s noteId=%s error=%s",
                contact_id,
                safe_note_id or "(resolved-latest)",
                result.get("error"),
            )
        return Response(
            {"received": True, "contactId": str(contact_id), "noteId": str(safe_note_id), "note_forward": result},
            status=status_code,
        )


class JobberClientSyncTagsToGhlView(APIView):
    """
    POST — Manually push Jobber client tags to GHL (same logic as CLIENT_UPDATE webhook).

    Body: { "jobber_client_id": "<encoded id>" }
    Auth: same as calendar sync (X-GHL-Calendar-Sync-Secret or admin).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        if not _can_run_ghl_calendar_sync(request):
            return Response(
                {"error": "Forbidden. Provide X-GHL-Calendar-Sync-Secret or authenticate as admin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        client_id = (request.data.get("jobber_client_id") or request.query_params.get("jobber_client_id") or "").strip()
        if not client_id:
            return Response({"error": "jobber_client_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        result = sync_jobber_client_tags_to_ghl(client_id)
        status_code = status.HTTP_200_OK if result.get("ok") or result.get("skipped") else status.HTTP_502_BAD_GATEWAY
        return Response({"tag_sync": result}, status=status_code)
