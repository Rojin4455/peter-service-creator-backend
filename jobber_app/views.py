"""
Basic test endpoints for Jobber integration.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .client import search_clients, create_client, get_visits, create_job, get_client_properties, create_property_for_client


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


class BookingConfirmView(APIView):
    """
    POST /api/jobber/booking/confirm/
    Unified booking confirmation: find or create client → resolve or create property → create job in Jobber.

    Request body (from Pricing Calculator):
      Client: first_name, last_name, email, phone (at least one of email/phone).
      Address: street1 (or service_address), city, province, postal_code; optional street2.
      Service: service_type (job title), package_title, package_description, approved_price; optional add_ons.
      Job details: bedrooms, bathrooms, square_footage, condition, pets, special_instructions, entry_instructions; optional estimated_labor_hours.
      Booking: scheduled_start_iso (ISO 8601) OR selected_date + selected_time.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        # Client
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        email = (data.get("email") or "").strip() or None
        phone = data.get("phone")
        if phone is not None:
            phone = str(phone).strip() or None
        # Address (for property create when needed)
        street1 = (data.get("street1") or data.get("service_address") or "").strip()
        city = (data.get("city") or "").strip()
        province = (data.get("province") or data.get("state") or "").strip()
        postal_code = (data.get("postal_code") or data.get("zip_code") or "").strip()
        street2 = (data.get("street2") or "").strip() or None
        # Service
        service_type = (data.get("service_type") or data.get("title") or "").strip()
        package_title = (data.get("package_title") or data.get("line_item_name") or "").strip()
        package_description = (data.get("package_description") or data.get("line_item_description") or "").strip()
        approved_price = data.get("approved_price") if data.get("approved_price") is not None else data.get("line_item_price")
        add_ons = (data.get("add_ons") or "").strip() or None
        # Booking time
        scheduled_start_iso = _parse_booking_datetime(
            data.get("selected_date"),
            data.get("selected_time"),
            data.get("scheduled_start_iso"),
        )
        # Validation
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
        if not service_type:
            return Response(
                {"error": "service_type (job title) is required (e.g. Residential First Clean)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not package_title:
            return Response(
                {"error": "package_title is required (e.g. Basic Package)"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if approved_price is None:
            return Response(
                {"error": "approved_price is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 1) Find or create client
        search_term = email or phone
        nodes, _, err = search_clients(search_term, first=5)
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        client_id = None
        client_created = False
        if nodes:
            # Use first match (by email or phone)
            client_id = nodes[0].get("id")
        if not client_id:
            client, err = create_client(first_name, last_name, email=email, phone=phone)
            if err:
                return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
            client_id = client.get("id")
            client_created = True

        # 2) Resolve or create property (need address for create)
        prop_id, _, err = get_client_properties(client_id)
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
        if not prop_id:
            if not street1 or not city or not province or not postal_code:
                return Response(
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
                return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)
            prop_id = prop.get("id")

        # 3) Build job notes and create job
        job_notes = _build_booking_job_notes(data)
        job, err = create_job(
            property_id=prop_id,
            title=service_type,
            line_item_name=package_title,
            line_item_description=package_description,
            line_item_price=approved_price,
            job_notes=job_notes,
            scheduled_start_iso=scheduled_start_iso,
        )
        if err:
            return Response({"error": err}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "client_id": client_id,
                "client_created": client_created,
                "property_id": prop_id,
                "job": job,
            },
            status=status.HTTP_201_CREATED,
        )
