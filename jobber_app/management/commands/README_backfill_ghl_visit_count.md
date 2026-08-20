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
