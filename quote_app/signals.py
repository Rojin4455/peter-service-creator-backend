"""
Signals to keep CustomerSubmission and GHL contact tags in sync.
Whenever submission.status is draft, submitted, or approved, the GHL contact
tag is updated to match (quote drafted, quote_requested, quote_accepted).
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CustomerSubmission


@receiver(post_save, sender=CustomerSubmission)
def sync_ghl_tags_on_submission_status_change(sender, instance, **kwargs):
    """
    After saving a CustomerSubmission, ensure the GHL contact tag matches
    status for draft / submitted / approved. This covers status changes from
    views, admin, shell, or any other code path.
    """
    if instance.is_on_the_go:
        return
    status = (instance.status or "").lower()
    if status in ("draft", "submitted", "approved"):
        from .helpers import sync_ghl_contact_tags_for_submission_status
        sync_ghl_contact_tags_for_submission_status(instance)
