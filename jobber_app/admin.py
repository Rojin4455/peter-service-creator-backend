from django.contrib import admin
from .models import JobberClientGhlTagSyncState, JobberVisitGhlBlockMap


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