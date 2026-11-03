from celery import shared_task

from jobber_app.visit_sync.sync import sync_visits as _sync_visits
from jobber_app.work_hours.sync import sync_work_hours as _sync_work_hours


@shared_task
def sync_work_hours():
    """Nightly: Jobber timesheets (last N local days) → Hub work hours."""
    return _sync_work_hours()


@shared_task
def sync_visits():
    """Nightly: Jobber visits (last N local days + updated invoices) → Hub visits. No-op until enabled."""
    return _sync_visits()
