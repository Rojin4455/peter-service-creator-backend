"""
One-time backfill: tag exact-matched GHL contacts + set Visit Count from Airtable visits CSV.

Default is dry-run (no GHL writes). Use --execute only after reviewing the report.
"""
import csv
import time
from datetime import datetime
from pathlib import Path

from decouple import config
from django.core.management.base import BaseCommand, CommandError

from jobber_app.ghl_contacts import (
    _get_credentials,
    _location_id,
    get_contact_by_id,
    normalize_ghl_tags,
    search_contacts,
    update_contact,
)
from jobber_app.visit_count_backfill import (
    DEFAULT_TAG,
    DEFAULT_VISIT_COUNT_FIELD_ID,
    contact_visit_count,
    fuzzy_match_unmatched,
    live_match_unmatched,
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
        parser.add_argument(
            "--live-lookup-unmatched",
            action="store_true",
            default=False,
            help="Search live GHL for CSV-unmatched names (export can be stale).",
        )
        parser.add_argument(
            "--only-live-unmatched",
            action="store_true",
            default=False,
            help="With --execute, write only live-lookup hits (not CSV exact matches).",
        )
        parser.add_argument(
            "--fuzzy-unmatched",
            action="store_true",
            default=False,
            help="Broader live GHL match on still-unmatched names (accents, titles, typos).",
        )
        parser.add_argument(
            "--unmatched-csv",
            default="",
            help="CSV with client,visit_count for --fuzzy-unmatched (default: last still_unmatched.csv).",
        )

    def handle(self, *args, **options):
        if options["execute"] and options["dry_run"]:
            raise CommandError("Pass either --execute or --dry-run, not both.")
        if options["fuzzy_unmatched"]:
            return self.handle_fuzzy(options)

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

        live = None
        if options["live_lookup_unmatched"]:
            loc = _location_id(_get_credentials())
            if not loc:
                raise CommandError("GHL_LOCATION_ID required for --live-lookup-unmatched")
            sleep_s = max(0.0, float(options["sleep"]))
            self.stdout.write(
                f"Live GHL search for {len(matched['unmatched'])} unmatched names…"
            )

            def search_fn(query):
                return search_contacts(loc, query)

            live = live_match_unmatched(
                matched["unmatched"],
                search_fn,
                tag=tag,
                sleep_s=sleep_s,
                on_progress=lambda i, n, name: self.stdout.write(
                    f"  live [{i}/{n}] {name}"
                ),
            )
            write_csv(
                out_dir / "live_would_update.csv",
                live["would_update"],
                [
                    "client",
                    "ghl_id",
                    "visit_count",
                    "already_has_tag",
                    "ghl_name",
                    "ghl_company",
                    "matched_client_count",
                    "source",
                ],
            )
            write_csv(
                out_dir / "live_skipped_multi.csv",
                live["multi"],
                ["client", "visit_count", "match_count", "ghl_ids"],
            )
            write_csv(
                out_dir / "still_unmatched.csv",
                live["still_unmatched"],
                ["client", "visit_count", "reason", "search_hits", "error"],
            )
            write_csv(
                out_dir / "live_search_errors.csv",
                live["errors"],
                ["client", "visit_count", "error"],
            )
            self.stdout.write(f"Live exact GHL IDs:     {len(live['would_update'])}")
            self.stdout.write(f"Live skipped multi:     {len(live['multi'])}")
            self.stdout.write(f"Still unmatched:        {len(live['still_unmatched'])}")
            self.stdout.write(f"Live search errors:     {len(live['errors'])}")

        if not execute:
            self.stdout.write(self.style.WARNING("DRY-RUN — no GHL writes."))
            self.stdout.write("Re-run with --execute after the would_update.csv looks right.")
            if options["live_lookup_unmatched"]:
                self.stdout.write(
                    "Live-unmatched only: --execute --live-lookup-unmatched --only-live-unmatched"
                )
            return

        successes = []
        failures = []
        sleep_s = max(0.0, float(options["sleep"]))
        if options["only_live_unmatched"]:
            if not live:
                raise CommandError("--only-live-unmatched requires --live-lookup-unmatched")
            rows = live["would_update"]
        else:
            rows = list(matched["would_update"])
            if live:
                seen = {r["ghl_id"] for r in rows}
                for r in live["would_update"]:
                    if r["ghl_id"] not in seen:
                        rows.append(r)
                        seen.add(r["ghl_id"])
                    else:
                        # same contact already in CSV match — keep CSV row
                        pass
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

    def handle_fuzzy(self, options):
        execute = bool(options["execute"])
        unmatched_path = Path(options["unmatched_csv"]) if options["unmatched_csv"] else Path(
            r"D:\Work\Saasyway\peter\service-creator\peter-service-creator-backend"
            r"\backfill_out\ghl_visit_count_execute_20260824_190201\still_unmatched.csv"
        )
        if not unmatched_path.is_file():
            raise CommandError(f"Unmatched CSV not found: {unmatched_path}")

        tag = (options["tag"] or DEFAULT_TAG).strip()
        field_id = (
            (options["visit_count_field_id"] or "").strip()
            or (config("GHL_VISIT_COUNT_FIELD_ID", default="") or "").strip()
            or DEFAULT_VISIT_COUNT_FIELD_ID
        )
        rows = []
        with open(unmatched_path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                client = (row.get("client") or "").strip()
                if not client:
                    continue
                try:
                    vc = int(float(row.get("visit_count") or 0))
                except ValueError:
                    vc = 0
                rows.append({"client": client, "visit_count": vc})

        loc = _location_id(_get_credentials())
        if not loc:
            raise CommandError("GHL_LOCATION_ID required for --fuzzy-unmatched")

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode = "execute" if execute else "dryrun"
        out_dir = Path(options["out_dir"]) if options["out_dir"] else Path("backfill_out") / (
            f"ghl_visit_count_fuzzy_{mode}_{stamp}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        sleep_s = max(0.0, float(options["sleep"]))
        self.stdout.write(f"Fuzzy live GHL search for {len(rows)} unmatched names…")
        self.stdout.write(f"Input: {unmatched_path}")

        def search_fn(query):
            return search_contacts(loc, query)

        fuzzy = fuzzy_match_unmatched(
            rows,
            search_fn,
            tag=tag,
            sleep_s=sleep_s,
            on_progress=lambda i, n, name: self.stdout.write(f"  fuzzy [{i}/{n}] {name}"),
        )

        synced_fields = [
            "original_clients",
            "client",
            "ghl_name",
            "ghl_id",
            "visit_count",
            "already_has_tag",
            "match_reason",
            "match_score",
            "ghl_company",
            "matched_client_count",
            "source",
        ]
        write_csv(out_dir / "fuzzy_would_update.csv", fuzzy["would_update"], synced_fields)
        write_csv(out_dir / "fuzzy_per_client.csv", fuzzy["exact_rows"], synced_fields)
        write_csv(
            out_dir / "fuzzy_skipped_multi.csv",
            fuzzy["multi"],
            ["client", "visit_count", "reason", "candidates"],
        )
        write_csv(
            out_dir / "fuzzy_still_unmatched.csv",
            fuzzy["still_unmatched"],
            ["client", "visit_count", "reason", "search_hits", "top_candidate"],
        )
        write_csv(out_dir / "fuzzy_skipped_internal.csv", fuzzy["skipped"], ["client", "visit_count", "reason"])

        self.stdout.write(f"Fuzzy unique matches:   {len(fuzzy['would_update'])}")
        self.stdout.write(f"Fuzzy client strings:   {len(fuzzy['exact_rows'])}")
        self.stdout.write(f"Fuzzy skipped multi:    {len(fuzzy['multi'])}")
        self.stdout.write(f"Still unmatched:        {len(fuzzy['still_unmatched'])}")
        self.stdout.write(f"Skipped internal:       {len(fuzzy['skipped'])}")
        self.stdout.write(f"Reports: {out_dir.resolve()}")

        if not execute:
            self.stdout.write(self.style.WARNING("DRY-RUN — no GHL writes."))
            self.stdout.write(
                "Execute: python manage.py backfill_ghl_visit_count --fuzzy-unmatched --execute --sleep 0.15"
            )
            return

        successes = []
        failures = []
        update_rows = fuzzy["would_update"]
        total = len(update_rows)
        self.stdout.write(self.style.WARNING(f"EXECUTE fuzzy — updating {total} GHL contacts…"))
        for i, row in enumerate(update_rows, start=1):
            gid = row["ghl_id"]
            planned = int(row["visit_count"])
            try:
                contact, err = get_contact_by_id(gid)
                if err or not contact:
                    failures.append({**row, "error": err or "contact not found"})
                    self.stderr.write(f"[{i}/{total}] FAIL get {gid}: {err}")
                    continue
                existing_count = contact_visit_count(contact, field_id)
                visit_count = max(existing_count, planned)
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
                live_name = (
                    f"{contact.get('firstName') or ''} {contact.get('lastName') or ''}".strip()
                    or (contact.get("name") or "")
                )
                result = {
                    **row,
                    "already_has_tag": already,
                    "prior_visit_count": existing_count,
                    "visit_count": visit_count,
                    "ghl_name_live": live_name,
                    "error": "" if ok else (uerr or "update failed"),
                }
                if ok:
                    successes.append(result)
                    self.stdout.write(
                        f"[{i}/{total}] OK {row.get('original_clients') or row.get('client')} "
                        f"-> {live_name or row.get('ghl_name')} "
                        f"visits={visit_count} (was {existing_count})"
                    )
                else:
                    failures.append(result)
                    self.stderr.write(f"[{i}/{total}] FAIL put {gid}: {uerr}")
            except Exception as exc:
                failures.append({**row, "error": str(exc)})
                self.stderr.write(f"[{i}/{total}] FAIL {gid}: {exc}")
            if sleep_s and i < total:
                time.sleep(sleep_s)

        synced_out = synced_fields + ["prior_visit_count", "ghl_name_live", "error"]
        write_csv(out_dir / "fuzzy_success.csv", successes, synced_out)
        write_csv(out_dir / "fuzzy_failed.csv", failures, synced_out)
        self.stdout.write(self.style.SUCCESS(f"Success: {len(successes)}"))
        if failures:
            self.stdout.write(self.style.ERROR(f"Failed:  {len(failures)}"))
        else:
            self.stdout.write("Failed:  0")
        self.stdout.write(f"Reports: {out_dir.resolve()}")
