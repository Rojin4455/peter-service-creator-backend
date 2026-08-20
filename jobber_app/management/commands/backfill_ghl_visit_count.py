"""
One-time backfill: tag exact-matched GHL contacts + set Visit Count from Airtable visits CSV.

Default is dry-run (no GHL writes). Use --execute only after reviewing the report.
"""
import time
from datetime import datetime
from pathlib import Path

from decouple import config
from django.core.management.base import BaseCommand, CommandError

from jobber_app.ghl_contacts import (
    get_contact_by_id,
    normalize_ghl_tags,
    update_contact,
)
from jobber_app.visit_count_backfill import (
    DEFAULT_TAG,
    DEFAULT_VISIT_COUNT_FIELD_ID,
    load_ghl_index,
    load_visits_counts,
    match_clients,
    write_csv,
)

DEFAULT_VISITS = r"d:\Downloads\Visits-All Visits.csv"
DEFAULT_GHL = r"d:\Downloads\GHL Contacts-Grid view.csv"


class Command(BaseCommand):
    help = (
        "Backfill GHL tag 'new client feedback sent' and Visit Count for exact-matched "
        "contacts from Airtable visits + GHL contacts CSVs. Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--visits-csv", default=DEFAULT_VISITS)
        parser.add_argument("--ghl-csv", default=DEFAULT_GHL)
        parser.add_argument(
            "--out-dir",
            default="",
            help="Directory for report CSVs (default: backfill_out/ghl_visit_count_<timestamp>)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="No GHL writes (default if --execute is omitted).",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            default=False,
            help="Write tag + Visit Count to GHL for exact matches only.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.2,
            help="Seconds to sleep between GHL writes (execute only).",
        )
        parser.add_argument(
            "--tag",
            default=DEFAULT_TAG,
            help="Tag to add (default: new client feedback sent).",
        )
        parser.add_argument(
            "--visit-count-field-id",
            default="",
            help="GHL custom field id (default: env GHL_VISIT_COUNT_FIELD_ID or known id).",
        )

    def handle(self, *args, **options):
        if options["execute"] and options["dry_run"]:
            raise CommandError("Pass either --execute or --dry-run, not both.")
        execute = bool(options["execute"])
        visits_csv = Path(options["visits_csv"])
        ghl_csv = Path(options["ghl_csv"])
        if not visits_csv.is_file():
            raise CommandError(f"Visits CSV not found: {visits_csv}")
        if not ghl_csv.is_file():
            raise CommandError(f"GHL CSV not found: {ghl_csv}")

        tag = (options["tag"] or DEFAULT_TAG).strip()
        field_id = (
            (options["visit_count_field_id"] or "").strip()
            or (config("GHL_VISIT_COUNT_FIELD_ID", default="") or "").strip()
            or DEFAULT_VISIT_COUNT_FIELD_ID
        )

        visit_counts = load_visits_counts(visits_csv)
        ghl_index, ghl_meta = load_ghl_index(ghl_csv)
        matched = match_clients(visit_counts, ghl_index, ghl_meta, tag=tag)

        out_dir = Path(options["out_dir"]) if options["out_dir"] else None
        if out_dir is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mode = "execute" if execute else "dryrun"
            out_dir = Path("backfill_out") / f"ghl_visit_count_{mode}_{stamp}"
        out_dir.mkdir(parents=True, exist_ok=True)

        write_csv(
            out_dir / "would_update.csv",
            matched["would_update"],
            [
                "client",
                "ghl_id",
                "visit_count",
                "already_has_tag",
                "ghl_name",
                "ghl_company",
                "matched_client_count",
            ],
        )
        write_csv(
            out_dir / "skipped_multi.csv",
            matched["multi"],
            ["client", "visit_count", "match_count", "ghl_ids"],
        )
        write_csv(
            out_dir / "skipped_unmatched.csv",
            matched["unmatched"],
            ["client", "visit_count"],
        )
        write_csv(
            out_dir / "merged_same_ghl_id.csv",
            matched["merged_same_ghl_id"],
            ["client", "ghl_id", "visit_count", "matched_client_count"],
        )

        self.stdout.write(f"Visits unique clients: {matched['unique_clients']}")
        self.stdout.write(f"Exact client strings:  {matched['exact_client_strings']}")
        self.stdout.write(f"Would update (GHL IDs): {len(matched['would_update'])}")
        self.stdout.write(f"Skipped multi:         {len(matched['multi'])}")
        self.stdout.write(f"Skipped unmatched:     {len(matched['unmatched'])}")
        self.stdout.write(
            f"Merged name-variants:  {len(matched['merged_same_ghl_id'])} "
            "(same GHL ID, visit_count summed)"
        )
        self.stdout.write(f"Tag: {tag}")
        self.stdout.write(f"Visit Count field id: {field_id}")
        self.stdout.write(f"Reports: {out_dir.resolve()}")

        if not execute:
            self.stdout.write(self.style.WARNING("DRY-RUN — no GHL writes."))
            self.stdout.write("Re-run with --execute after the would_update.csv looks right.")
            return

        successes = []
        failures = []
        sleep_s = max(0.0, float(options["sleep"]))
        rows = matched["would_update"]
        total = len(rows)
        self.stdout.write(self.style.WARNING(f"EXECUTE — updating {total} GHL contacts…"))

        for i, row in enumerate(rows, start=1):
            gid = row["ghl_id"]
            visit_count = int(row["visit_count"])
            try:
                contact, err = get_contact_by_id(gid)
                if err or not contact:
                    failures.append({**row, "error": err or "contact not found"})
                    self.stderr.write(f"[{i}/{total}] FAIL get {gid}: {err}")
                    continue
                existing = normalize_ghl_tags(contact)
                already = any(t.lower() == tag.lower() for t in existing)
                merged_tags = list(existing)
                if not already:
                    merged_tags.append(tag)
                ok, uerr = update_contact(
                    gid,
                    tags=merged_tags,
                    custom_fields=[{"id": field_id, "field_value": str(visit_count)}],
                )
                result = {
                    **row,
                    "already_has_tag": already,
                    "error": "" if ok else (uerr or "update failed"),
                }
                if ok:
                    successes.append(result)
                    self.stdout.write(
                        f"[{i}/{total}] OK {gid} visits={visit_count} tag_existed={already}"
                    )
                else:
                    failures.append(result)
                    self.stderr.write(f"[{i}/{total}] FAIL put {gid}: {uerr}")
            except Exception as exc:
                failures.append({**row, "error": str(exc)})
                self.stderr.write(f"[{i}/{total}] FAIL {gid}: {exc}")
            if sleep_s and i < total:
                time.sleep(sleep_s)

        write_csv(
            out_dir / "success.csv",
            successes,
            [
                "client",
                "ghl_id",
                "visit_count",
                "already_has_tag",
                "matched_client_count",
                "error",
            ],
        )
        write_csv(
            out_dir / "failed.csv",
            failures,
            [
                "client",
                "ghl_id",
                "visit_count",
                "already_has_tag",
                "matched_client_count",
                "error",
            ],
        )
        self.stdout.write(self.style.SUCCESS(f"Success: {len(successes)}"))
        if failures:
            self.stdout.write(self.style.ERROR(f"Failed:  {len(failures)}"))
        else:
            self.stdout.write("Failed:  0")
        self.stdout.write(f"Reports: {out_dir.resolve()}")
