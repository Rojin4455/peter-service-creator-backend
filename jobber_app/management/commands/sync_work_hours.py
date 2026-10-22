"""
Run the Jobber timesheets → Hub work-hours sync once (same code as the nightly Celery task).

  python manage.py sync_work_hours --dry-run   # fetch + aggregate only, no Hub calls, no DB writes
  python manage.py sync_work_hours             # send to the Hub
"""
import json

from django.core.management.base import BaseCommand, CommandError

from jobber_app.work_hours.sync import sync_work_hours


class Command(BaseCommand):
    help = "Sync Jobber timesheet hours (per employee per local day) to the Hub."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and aggregate only; print a summary without calling the Hub.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Lookback in local days (default WORK_HOURS_LOOKBACK_DAYS or 14).",
        )

    def handle(self, *args, **options):
        if options["days"] is not None and options["days"] < 1:
            raise CommandError("--days must be at least 1")
        summary = sync_work_hours(days=options["days"], dry_run=options["dry_run"])
        self.stdout.write(json.dumps(summary, indent=2))
        if not summary.get("ok"):
            raise CommandError(summary.get("error") or "Work hours sync failed")
