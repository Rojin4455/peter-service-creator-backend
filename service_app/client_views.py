"""
Admin Clients tab API — group submissions by contact identity.
"""
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from quote_app.client_utils import (
    annotate_client_key,
    client_key_for_submission,
    ghl_contact_snapshot,
    grouped_clients_queryset,
    latest_submission_for_client,
    profile_from_submission,
    submissions_for_client_id,
)
from quote_app.helpers import create_or_update_ghl_contact, sync_ghl_contact_tags_for_submission_status
from quote_app.models import CustomerSubmission
from quote_app.serializers import CustomerSubmissionDetailSerializer

from .serializers import (
    AdminClientSubmissionUpdateSerializer,
    ClientProfileUpdateSerializer,
    CustomerSubmissionListSerializer,
)
from .views import SubmissionPagination


def _client_list_item(row, latest_submission):
    profile = profile_from_submission(latest_submission)
    return {
        "client_id": row["client_id"],
        "client_key": row["client_key"],
        "submission_count": row["submission_count"],
        "approved_count": row["approved_count"] or 0,
        "total_revenue": float(row["total_revenue"] or 0),
        "latest_submission_at": (
            row["latest_submission_at"].isoformat() if row["latest_submission_at"] else None
        ),
        "full_name": profile.get("full_name"),
        "email": profile.get("email"),
        "phone": profile.get("phone"),
        "company_name": profile.get("company_name"),
        "ghl_contact_id": profile.get("ghl_contact_id"),
    }


def _client_detail_payload(client_id, *, include_on_the_go=False):
    latest = latest_submission_for_client(client_id, include_on_the_go=include_on_the_go)
    if latest is None:
        return None

    submissions_qs = submissions_for_client_id(client_id, include_on_the_go=include_on_the_go)
    stats = submissions_qs.aggregate(
        submission_count=Count("id"),
        approved_count=Count("id", filter=Q(status="approved")),
        total_revenue=Sum("final_total", filter=Q(status="approved")),
    )
    profile = profile_from_submission(latest)

    return {
        "client_id": client_id,
        "client_key": client_key_for_submission(latest),
        "profile": profile,
        "ghl_contact": ghl_contact_snapshot(profile.get("ghl_contact_id")),
        "stats": {
            "submission_count": stats["submission_count"] or 0,
            "approved_count": stats["approved_count"] or 0,
            "total_revenue": float(stats["total_revenue"] or 0),
        },
        "latest_submission_id": str(latest.id),
        "latest_submission_at": latest.created_at.isoformat() if latest.created_at else None,
    }


class ClientListView(APIView):
    """Paginated list of clients derived from CustomerSubmission groupings."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get("search")
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"

        grouped = list(
            grouped_clients_queryset(
                include_on_the_go=include_on_the_go,
                search=search,
            )
        )

        paginator = SubmissionPagination()
        page = paginator.paginate_queryset(grouped, request)
        rows = page if page is not None else grouped

        latest_map = {}
        if rows:
            client_ids = [row["client_id"] for row in rows]
            base_qs = CustomerSubmission.objects.all()
            if not include_on_the_go:
                base_qs = base_qs.filter(is_on_the_go=False)
            candidates = (
                annotate_client_key(base_qs)
                .filter(client_id__in=client_ids)
                .select_related("location")
                .order_by("client_id", "-created_at")
            )
            for sub in candidates:
                if sub.client_id not in latest_map:
                    latest_map[sub.client_id] = sub

        results = [_client_list_item(row, latest_map.get(row["client_id"])) for row in rows]

        if page is not None:
            return paginator.get_paginated_response(results)
        return Response(results, status=status.HTTP_200_OK)


class ClientDetailView(APIView):
    """Client profile, optional GHL mirror data, and aggregate stats."""
    permission_classes = [IsAuthenticated]

    def get(self, request, client_id):
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"
        payload = _client_detail_payload(client_id, include_on_the_go=include_on_the_go)
        if payload is None:
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload, status=status.HTTP_200_OK)

    def patch(self, request, client_id):
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"
        submissions_qs = submissions_for_client_id(client_id, include_on_the_go=include_on_the_go)
        if not submissions_qs.exists():
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ClientProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        update_data = dict(serializer.validated_data)

        if "location" in update_data:
            from service_app.models import Location

            loc_id = update_data.pop("location")
            if loc_id is None:
                update_data["location_id"] = None
            else:
                loc = get_object_or_404(Location, id=loc_id)
                update_data["location_id"] = loc.id

        edited_by = None
        if request.user.is_authenticated:
            edited_by = getattr(request.user, "username", None) or getattr(request.user, "email", None)

        updated_count = submissions_qs.update(**update_data)

        latest = submissions_qs.order_by("-created_at").first()
        if latest:
            latest.last_edited_at = timezone.now()
            latest.edited_by = edited_by or latest.edited_by
            latest.save(update_fields=["last_edited_at", "edited_by", "updated_at"])
            try:
                create_or_update_ghl_contact(latest)
            except Exception:
                pass

        payload = _client_detail_payload(client_id, include_on_the_go=include_on_the_go)
        return Response(
            {
                "message": "Client profile updated successfully.",
                "updated_submission_count": updated_count,
                "client": payload,
            },
            status=status.HTTP_200_OK,
        )


class ClientSubmissionsListView(APIView):
    """Paginated submission history for a client."""
    permission_classes = [IsAuthenticated]

    def get(self, request, client_id):
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"
        status_filter = request.query_params.get("status")

        qs = (
            submissions_for_client_id(client_id, include_on_the_go=include_on_the_go)
            .select_related("location")
            .prefetch_related("customerserviceselection_set__service")
            .order_by("-created_at")
        )
        if not qs.exists():
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        if status_filter:
            qs = qs.filter(status=status_filter)

        paginator = SubmissionPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = CustomerSubmissionListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class ClientSubmissionDetailView(APIView):
    """
    Full submission detail for editing within the Clients tab.
    Deep pricing / response edits use existing /api/quote/ endpoints.
    """
    permission_classes = [IsAuthenticated]

    def _submission_queryset(self, client_id, include_on_the_go=False):
        return (
            submissions_for_client_id(client_id, include_on_the_go=include_on_the_go)
            .select_related("location", "size_range", "applied_coupon", "applied_bundle")
            .prefetch_related(
                "customerserviceselection_set__service",
                "customerserviceselection_set__package_quotes__package",
                "customerserviceselection_set__question_responses__question",
                "customerserviceselection_set__question_responses__option_responses__option",
                "customerserviceselection_set__question_responses__sub_question_responses__sub_question",
                "customerserviceselection_set__question_responses__measurement_responses__option",
                "submission_addons__addon",
                "images",
                "availabilities",
            )
        )

    def get(self, request, client_id, submission_id):
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"
        submission = get_object_or_404(
            self._submission_queryset(client_id, include_on_the_go),
            id=submission_id,
        )
        data = CustomerSubmissionDetailSerializer(submission, context={"request": request}).data
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request, client_id, submission_id):
        include_on_the_go = request.query_params.get("include_on_the_go", "").lower() == "true"
        submission = get_object_or_404(
            self._submission_queryset(client_id, include_on_the_go),
            id=submission_id,
        )

        serializer = AdminClientSubmissionUpdateSerializer(
            submission,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        old_status = submission.status
        submission = serializer.save()

        edited_by = None
        if request.user.is_authenticated:
            edited_by = getattr(request.user, "username", None) or getattr(request.user, "email", None)
        submission.last_edited_at = timezone.now()
        submission.edited_by = edited_by or submission.edited_by
        submission.save(update_fields=["last_edited_at", "edited_by", "updated_at"])

        if old_status != submission.status:
            try:
                sync_ghl_contact_tags_for_submission_status(submission)
            except Exception:
                pass

        try:
            create_or_update_ghl_contact(submission)
        except Exception:
            pass

        data = CustomerSubmissionDetailSerializer(submission, context={"request": request}).data
        return Response(
            {
                "message": "Submission updated successfully.",
                "submission": data,
            },
            status=status.HTTP_200_OK,
        )
