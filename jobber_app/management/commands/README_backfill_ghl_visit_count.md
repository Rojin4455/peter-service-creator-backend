# GHL Visit Count + tag backfill

One-time command. Exact name matches only. No Jobber lookup. Does not create contacts.

## Dry-run (default, no GHL writes)

From `peter-service-creator-backend`:

```bash
python manage.py backfill_ghl_visit_count
```

Optional explicit flag / paths:

```bash
python manage.py backfill_ghl_visit_count --dry-run ^
  --visits-csv "d:\Downloads\Visits-All Visits.csv" ^
  --ghl-csv "d:\Downloads\GHL Contacts-Grid view.csv"
```

Writes CSVs under `backfill_out/ghl_visit_count_dryrun_<timestamp>/`:

- `would_update.csv` — Client, GHL ID, visit_count, already_has_tag (from GHL CSV Tags column)
- `skipped_multi.csv` — 2+ GHL IDs for the same name
- `skipped_unmatched.csv` — no GHL name/company hit
- `merged_same_ghl_id.csv` — two visit Client strings (usually extra spaces) → same GHL ID; visit_count is summed

## Execute (writes GHL)

Only after dry-run counts look right:

```bash
python manage.py backfill_ghl_visit_count --execute --sleep 0.2
```

Per contact: GET tags, merge `new client feedback sent` (keep other tags), PUT Visit Count field `14nLMLzzIPvF65shBM9w`. Safe to re-run (idempotent).

Uses existing GHL PIT / OAuth via `jobber_app.ghl_contacts`.

## CSV-unmatched that exist in live GHL

The contacts export can be stale. Example: **Donata De Luca** has 12 visit rows but was missing from the GHL CSV, so the first pass skipped her. Live GHL has the contact; Visit Count was `1` (workflow treats her as new) instead of 12.

Dry-run live name search (exact unique match only, same rules):

```bash
python manage.py backfill_ghl_visit_count --live-lookup-unmatched --sleep 0.2
```

Writes `live_would_update.csv` and `still_unmatched.csv`.

Execute **only** those live hits (does not write the original CSV matches):

```bash
python manage.py backfill_ghl_visit_count --execute --live-lookup-unmatched --only-live-unmatched --sleep 0.2
```

## Manual fix in GHL (Peter)

1. Open the contact (search the Jobber client name).
2. Add tag exactly: `new client feedback sent` (leave other tags).
3. Set custom field **Visit Count** to the number of rows for that client in the Visits table (all statuses).
4. Save. Next visit-complete should use the regular-client workflow, not the new-client one.
