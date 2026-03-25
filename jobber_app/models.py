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
