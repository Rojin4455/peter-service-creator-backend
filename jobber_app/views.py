"""
Basic test endpoints for Jobber integration.
"""
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny

from .client import search_clients, create_client, get_visits, create_job, get_client_properties


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
