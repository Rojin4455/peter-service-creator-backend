"""
Run the Jobber visits → Hub sync once (same code as the nightly Celery task).

  python manage.py sync_visits --dry-run   # read Jobber and build rows only; no Hub calls, no DB writes
  python manage.py sync_visits             # send to the Hub (requires VISITS_SYNC_ENABLED=true)
"""
import json

from django.core.management.base import BaseCommand, CommandError

from jobber_app.visit_sync.sync import sync_visits


class Command(BaseCommand):
    help = "Sync Jobber visits (amounts for contractor pay) to the Hub."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Read Jobber and build rows only; print a summary without calling the Hub.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Lookback in local days (default VISITS_LOOKBACK_DAYS or 30).",
        )
        parser.add_argument(
            "--forward",
            type=int,
            default=None,
            help="Days ahead to include scheduled visits (default VISITS_FORWARD_DAYS or 42).",
        )

    def handle(self, *args, **options):
        if options["days"] is not None and options["days"] < 1:
            raise CommandError("--days must be at least 1")
        if options["forward"] is not None and options["forward"] < 0:
            raise CommandError("--forward must be 0 or more")
        summary = sync_visits(
            days=options["days"], forward=options["forward"], dry_run=options["dry_run"]
        )
        self.stdout.write(json.dumps(summary, indent=2, default=str))
        if not summary.get("ok"):
            raise CommandError(summary.get("error") or "Visits sync failed")
