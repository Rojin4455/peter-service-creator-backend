from django.urls import path
from . import views

urlpatterns = [
    path("clients/search/", views.JobberSearchClientsView.as_view(), name="jobber-search-clients"),
    path("clients/create/", views.JobberCreateClientView.as_view(), name="jobber-create-client"),
    path("properties/create/", views.JobberCreatePropertyView.as_view(), name="jobber-create-property"),
    path("visits/", views.JobberVisitsView.as_view(), name="jobber-visits"),
    path("jobs/create/", views.JobberCreateJobView.as_view(), name="jobber-create-job"),
    path("booking/slot-info/", views.BookingSlotInfoView.as_view(), name="booking-slot-info"),
    path("booking/confirm/", views.BookingConfirmView.as_view(), name="booking-confirm"),
    path("webhooks/jobber/", views.JobberWebhookView.as_view(), name="jobber-webhook"),
    path(
        "webhooks/ghl/contact-tags/",
        views.GhlContactTagsWebhookView.as_view(),
        name="ghl-contact-tags-webhook",
    ),
    path(
        "webhooks/ghl/contact-note/",
        views.GhlContactNoteWebhookView.as_view(),
        name="ghl-contact-note-webhook",
    ),
    path(
        "clients/sync-tags-to-ghl/",
        views.JobberClientSyncTagsToGhlView.as_view(),
        name="jobber-client-sync-tags-to-ghl",
    ),
    path(
        "calendar/sync-from-jobber/",
        views.GhlCalendarSyncFromJobberView.as_view(),
        name="ghl-calendar-sync-from-jobber",
    ),
]
