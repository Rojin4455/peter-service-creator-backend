"""
Group CustomerSubmission rows into admin "clients" for the Clients tab.

Identity priority: ghl_contact_id → email → phone → single submission fallback.
"""
import hashlib
import re

from django.db.models import Count, Max, Q, Sum
from django.db.models.expressions import RawSQL

from quote_app.models import CustomerSubmission

# PostgreSQL expression — must stay in sync with client_key_for_submission().
# All columns are table-qualified so RawSQL stays valid when JOINs exist (e.g. select_related).
_CS = "customer_submissions"
CLIENT_KEY_SQL = f"""
CASE
  WHEN {_CS}.ghl_contact_id IS NOT NULL AND TRIM({_CS}.ghl_contact_id) <> ''
    THEN 'ghl:' || TRIM({_CS}.ghl_contact_id)
  WHEN {_CS}.customer_email IS NOT NULL AND TRIM({_CS}.customer_email) <> ''
    THEN 'email:' || LOWER(TRIM({_CS}.customer_email))
  WHEN {_CS}.customer_phone IS NOT NULL AND TRIM({_CS}.customer_phone) <> ''
    THEN 'phone:' || regexp_replace({_CS}.customer_phone, '[^0-9]', '', 'g')
  ELSE 'sub:' || {_CS}.id::text
END
"""

CLIENT_ID_SQL = f"md5(({CLIENT_KEY_SQL})::text)"


def normalize_phone(phone):
    if not phone:
        return ""
    return re.sub(r"\D", "", str(phone))


def client_key_for_submission(submission):
    """Python mirror of CLIENT_KEY_SQL for a single submission instance."""
    if submission.ghl_contact_id and str(submission.ghl_contact_id).strip():
        return f"ghl:{submission.ghl_contact_id.strip()}"
    if submission.customer_email and str(submission.customer_email).strip():
        return f"email:{submission.customer_email.strip().lower()}"
    digits = normalize_phone(submission.customer_phone)
    if digits:
        return f"phone:{digits}"
    return f"sub:{submission.id}"


def client_id_from_key(client_key):
    return hashlib.md5(client_key.encode("utf-8")).hexdigest()


def base_submissions_queryset(*, include_on_the_go=False):
    qs = CustomerSubmission.objects.all()
    if not include_on_the_go:
        qs = qs.filter(is_on_the_go=False)
    return qs


def annotate_client_key(queryset):
    return queryset.annotate(
        client_key=RawSQL(CLIENT_KEY_SQL, []),
        client_id=RawSQL(CLIENT_ID_SQL, []),
    )


def submissions_for_client_id(client_id, *, include_on_the_go=False):
    return annotate_client_key(base_submissions_queryset(include_on_the_go=include_on_the_go)).filter(
        client_id=client_id
    )


def grouped_clients_queryset(*, include_on_the_go=False, search=None):
    qs = annotate_client_key(base_submissions_queryset(include_on_the_go=include_on_the_go))

    if search:
        term = search.strip()
        if term:
            qs = qs.filter(
                Q(first_name__icontains=term)
                | Q(last_name__icontains=term)
                | Q(customer_email__icontains=term)
                | Q(customer_phone__icontains=term)
                | Q(company_name__icontains=term)
                | Q(ghl_contact_id__icontains=term)
            )

    return (
        qs.values("client_key", "client_id")
        .annotate(
            submission_count=Count("pk"),
            latest_submission_at=Max("created_at"),
            approved_count=Count("pk", filter=Q(status="approved")),
            total_revenue=Sum("final_total", filter=Q(status="approved")),
        )
        .order_by("-latest_submission_at")
    )


def latest_submission_for_client(client_id, *, include_on_the_go=False):
    return (
        submissions_for_client_id(client_id, include_on_the_go=include_on_the_go)
        .select_related("location", "size_range")
        .order_by("-created_at")
        .first()
    )


def profile_from_submission(submission):
    if submission is None:
        return {}
    full_name = f"{submission.first_name or ''} {submission.last_name or ''}".strip()
    return {
        "first_name": submission.first_name,
        "last_name": submission.last_name,
        "full_name": full_name or None,
        "company_name": submission.company_name,
        "email": submission.customer_email,
        "phone": submission.customer_phone,
        "postal_code": submission.postal_code,
        "street_address": submission.street_address,
        "ghl_contact_id": submission.ghl_contact_id,
        "allow_sms": submission.allow_sms,
        "allow_email": submission.allow_email,
        "city": submission.location.name if submission.location else None,
        "location_id": str(submission.location_id) if submission.location_id else None,
    }


def ghl_contact_snapshot(ghl_contact_id):
    """Optional enrichment from accounts.Contact (GHL mirror), when populated."""
    if not ghl_contact_id:
        return None
    try:
        from accounts.models import Contact

        row = Contact.objects.filter(contact_id=ghl_contact_id).first()
    except Exception:
        return None
    if not row:
        return None
    return {
        "contact_id": row.contact_id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "phone": row.phone,
        "tags": row.tags or [],
        "dnd": row.dnd,
        "date_added": row.date_added.isoformat() if row.date_added else None,
    }
