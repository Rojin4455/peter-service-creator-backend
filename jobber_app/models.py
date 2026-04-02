"""
Models for Jobber ↔ external integrations (e.g. GHL calendar block sync).
"""
from django.db import models


class JobberVisitGhlBlockMap(models.Model):
    """
    Maps a Jobber visit (schedule item) to a GoHighLevel calendar block event,
    so we can update/delete GHL blocks idempotently when Jobber visits change.
    """

    jobber_visit_id = models.CharField(max_length=255, unique=True, db_index=True)
    ghl_event_id = models.CharField(max_length=255, db_index=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    title = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "jobber_visit_ghl_block_map"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.jobber_visit_id} → {self.ghl_event_id}"


class JobberClientGhlTagSyncState(models.Model):
    """
    Tracks last tag sync direction/signature for a Jobber client to reduce ping-pong
    when both Jobber and GHL fire updates after we push.
    """

    jobber_client_id = models.CharField(max_length=255, unique=True, db_index=True)
    ghl_contact_id = models.CharField(max_length=255, blank=True, default="")
    last_jobber_tag_signature = models.CharField(max_length=64, blank=True, default="")
    last_ghl_tag_signature = models.CharField(max_length=64, blank=True, default="")
    last_sync_source = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="'jobber' or 'ghl' — which system we last pushed from.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "jobber_client_ghl_tag_sync_state"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.jobber_client_id} ↔ {self.ghl_contact_id or '?'}"


class JobberGhlNoteForward(models.Model):
    """
    One row per GHL CRM note successfully applied to Jobber (idempotency for webhooks/retries).
    """

    ghl_note_id = models.CharField(max_length=128, unique=True, db_index=True)
    ghl_contact_id = models.CharField(max_length=128, db_index=True)
    jobber_client_id = models.CharField(max_length=255, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "jobber_ghl_note_forward"
        ordering = ["-created_at"]

    def __str__(self):
        return f"GHL note {self.ghl_note_id} → Jobber {self.jobber_client_id}"


class GhlAppointmentJobberJobMap(models.Model):
    """
    Idempotency: one Jobber job per GHL calendar appointment when booking webhook runs
    (workflow retries / duplicate deliveries).
    """

    ghl_appointment_id = models.CharField(max_length=255, unique=True, db_index=True)
    jobber_job_id = models.CharField(max_length=255, db_index=True)
    submission_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ghl_appointment_jobber_job_map"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.ghl_appointment_id} → Jobber job {self.jobber_job_id}"
