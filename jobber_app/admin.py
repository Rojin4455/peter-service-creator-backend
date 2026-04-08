from django.contrib import admin
from .models import (
    GhlAppointmentJobberJobMap,
    JobberClientGhlTagSyncState,
    JobberGhlNoteForward,
    JobberVisitGhlBlockMap,
)


@admin.register(JobberGhlNoteForward)
class JobberGhlNoteForwardAdmin(admin.ModelAdmin):
    list_display = ("ghl_note_id", "ghl_contact_id", "jobber_client_id", "created_at")
    search_fields = ("ghl_note_id", "ghl_contact_id", "jobber_client_id")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


@admin.register(JobberClientGhlTagSyncState)
class JobberClientGhlTagSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "jobber_client_id",
        "ghl_contact_id",
        "last_sync_source",
        "updated_at",
    )
    search_fields = ("jobber_client_id", "ghl_contact_id")
    list_filter = ("last_sync_source",)
    ordering = ("-updated_at",)
    readonly_fields = ("updated_at",)


@admin.register(GhlAppointmentJobberJobMap)
class GhlAppointmentJobberJobMapAdmin(admin.ModelAdmin):
    list_display = (
        "ghl_appointment_id",
        "submission_id",
        "jobber_job_id",
        "booking_start_at",
        "calendar_timezone",
        "created_at",
    )
    search_fields = ("ghl_appointment_id", "jobber_job_id", "submission_id")
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


@admin.register(JobberVisitGhlBlockMap)
class JobberVisitGhlBlockMapAdmin(admin.ModelAdmin):
    list_display = ("jobber_visit_id", "ghl_event_id", "start_at", "end_at")
    search_fields = ("jobber_visit_id", "ghl_event_id")
    list_filter = ("start_at", "end_at")
    date_hierarchy = "start_at"
    ordering = ("-start_at",)
    list_per_page = 100
    list_max_show_all = 100
    list_editable = ("start_at", "end_at")
    list_display_links = ("jobber_visit_id", "ghl_event_id")
    # These are CharFields, not FK relations.
    list_select_related = ()