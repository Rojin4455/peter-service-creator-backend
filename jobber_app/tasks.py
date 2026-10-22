from celery import shared_task

from jobber_app.work_hours.sync import sync_work_hours as _sync_work_hours


@shared_task
def sync_work_hours():
    """Nightly: Jobber timesheets (last N local days) → Hub work hours."""
    return _sync_work_hours()
