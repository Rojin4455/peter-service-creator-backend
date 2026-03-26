from django.contrib import admin
from .models import JobberVisitGhlBlockMap

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
    list_select_related = ("jobber_visit", "ghl_event")