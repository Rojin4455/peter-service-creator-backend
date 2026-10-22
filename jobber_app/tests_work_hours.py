from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from jobber_app.models import WorkHoursSentDay
from jobber_app.work_hours import hub_client, jobber
from jobber_app.work_hours.aggregate import (
    aggregate_entries,
    seconds_to_hours,
    split_by_local_day,
)
from jobber_app.work_hours.sync import sync_work_hours

TORONTO = ZoneInfo("America/Toronto")
DRIVE = frozenset({"DRIVING"})
U1 = "Z2lkOi8vSm9iYmVyL1VzZXIvMQ=="
U2 = "Z2lkOi8vSm9iYmVyL1VzZXIvMg=="


def _entry(user, start, end, category="GENERAL", ticking=False, duration=None):
    """start/end: naive Toronto-local datetimes (end may be None)."""
    start_utc = start.replace(tzinfo=TORONTO).astimezone(timezone.utc)
    end_utc = end.replace(tzinfo=TORONTO).astimezone(timezone.utc) if end else None
    if duration is None:
        duration = int((end_utc - start_utc).total_seconds()) if end_utc else 0
    return {
        "id": f"e-{user}-{start.isoformat()}",
        "startAt": start_utc.isoformat().replace("+00:00", "Z"),
        "endAt": end_utc.isoformat().replace("+00:00", "Z") if end_utc else None,
        "finalDuration": 0 if ticking else duration,
        "ticking": ticking,
        "timeSheetCategory": category,
        "user": {"id": user},
    }


class WorkHoursAggregateTests(SimpleTestCase):
    window = (date(2026, 10, 1), date(2026, 10, 31))

    def test_splits_regular_and_drive_and_excludes_break_and_running(self):
        entries = [
            _entry(U1, datetime(2026, 10, 20, 9), datetime(2026, 10, 20, 12)),
            _entry(U1, datetime(2026, 10, 20, 12), datetime(2026, 10, 20, 13, 15), "DRIVING"),
            _entry(U1, datetime(2026, 10, 20, 13, 15), datetime(2026, 10, 20, 13, 45), "BREAK"),
            _entry(U1, datetime(2026, 10, 20, 14), datetime(2026, 10, 20, 15), "OFFICE"),
            _entry(U1, datetime(2026, 10, 20, 16), None, ticking=True),
            {**_entry(U2, datetime(2026, 10, 20, 9), datetime(2026, 10, 20, 10)), "timeSheetCategory": None},
        ]
        totals, stats = aggregate_entries(entries, TORONTO, DRIVE, *self.window)
        self.assertEqual(totals[(U1, date(2026, 10, 20))], {"regular": 4 * 3600, "drive": 4500})
        self.assertEqual(totals[(U2, date(2026, 10, 20))], {"regular": 3600, "drive": 0})
        self.assertEqual(stats["skipped_break"], 1)
        self.assertEqual(stats["skipped_running"], 1)

    def test_drive_categories_are_configurable(self):
        entries = [_entry(U1, datetime(2026, 10, 20, 9), datetime(2026, 10, 20, 10))]
        totals, _ = aggregate_entries(entries, TORONTO, frozenset({"GENERAL"}), *self.window)
        self.assertEqual(totals[(U1, date(2026, 10, 20))], {"regular": 0, "drive": 3600})

    def test_entry_crossing_midnight_is_split_by_local_day(self):
        entries = [_entry(U1, datetime(2026, 10, 20, 22), datetime(2026, 10, 21, 1, 30))]
        totals, _ = aggregate_entries(entries, TORONTO, DRIVE, *self.window)
        self.assertEqual(totals[(U1, date(2026, 10, 20))]["regular"], 2 * 3600)
        self.assertEqual(totals[(U1, date(2026, 10, 21))]["regular"], 1.5 * 3600)

    def test_only_days_inside_window_are_kept(self):
        entries = [_entry(U1, datetime(2026, 9, 30, 23), datetime(2026, 10, 1, 2))]
        totals, _ = aggregate_entries(entries, TORONTO, DRIVE, *self.window)
        self.assertEqual(list(totals), [(U1, date(2026, 10, 1))])
        self.assertEqual(totals[(U1, date(2026, 10, 1))]["regular"], 2 * 3600)

    def test_entry_without_end_uses_final_duration_on_start_date(self):
        entries = [_entry(U1, datetime(2026, 10, 20, 9), None, duration=5400)]
        totals, _ = aggregate_entries(entries, TORONTO, DRIVE, *self.window)
        self.assertEqual(totals[(U1, date(2026, 10, 20))]["regular"], 5400)

    def test_dst_fall_back_day_counts_real_elapsed_time(self):
        start = datetime(2026, 11, 1, tzinfo=TORONTO)
        end = datetime(2026, 11, 2, tzinfo=TORONTO)
        self.assertEqual(list(split_by_local_day(start, end, TORONTO)), [(date(2026, 11, 1), 25 * 3600)])

    def test_seconds_to_hours_rounds_to_two_decimals(self):
        self.assertEqual(seconds_to_hours(4500), Decimal("1.25"))
        self.assertEqual(seconds_to_hours(27000), Decimal("7.50"))
        self.assertEqual(seconds_to_hours(18), Decimal("0.01"))
        self.assertEqual(seconds_to_hours(0), Decimal("0.00"))


@patch("jobber_app.work_hours.jobber.time.sleep")
@patch("jobber_app.work_hours.jobber._request")
class WorkHoursJobberFetchTests(SimpleTestCase):
    after = datetime(2026, 10, 7, 4, tzinfo=timezone.utc)
    before = datetime(2026, 10, 22, 4, tzinfo=timezone.utc)

    def _page(self, nodes, cursor=None):
        return {
            "timeSheetEntries": {
                "nodes": nodes,
                "pageInfo": {"hasNextPage": bool(cursor), "endCursor": cursor},
            }
        }, None

    def test_paginates_with_date_filter(self, mock_req, mock_sleep):
        mock_req.side_effect = [self._page([{"id": "1"}], "c1"), self._page([{"id": "2"}])]
        entries, err = jobber.fetch_time_sheet_entries(self.after, self.before)
        self.assertIsNone(err)
        self.assertEqual([e["id"] for e in entries], ["1", "2"])
        first_vars = mock_req.call_args_list[0].args[1]
        self.assertEqual(
            first_vars["filter"]["startAt"],
            {"after": self.after.isoformat(), "before": self.before.isoformat()},
        )
        self.assertNotIn("after", first_vars)
        self.assertEqual(mock_req.call_args_list[1].args[1]["after"], "c1")
        mock_sleep.assert_not_called()

    def test_retries_on_429_and_throttle(self, mock_req, mock_sleep):
        mock_req.side_effect = [
            (None, "Jobber API HTTP 429: Too Many Requests"),
            (None, "Throttled"),
            self._page([{"id": "1"}]),
        ]
        entries, err = jobber.fetch_time_sheet_entries(self.after, self.before)
        self.assertIsNone(err)
        self.assertEqual(len(entries), 1)
        self.assertEqual([c.args[0] for c in mock_sleep.call_args_list], [2, 4])

    def test_does_not_retry_other_errors(self, mock_req, mock_sleep):
        mock_req.return_value = (None, "Field 'x' doesn't exist")
        entries, err = jobber.fetch_time_sheet_entries(self.after, self.before)
        self.assertEqual(entries, [])
        self.assertIn("doesn't exist", err)
        self.assertEqual(mock_req.call_count, 1)
        mock_sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self, mock_req, mock_sleep):
        mock_req.return_value = (None, "Jobber API HTTP 503: unavailable")
        entries, err = jobber.fetch_time_sheet_entries(self.after, self.before)
        self.assertEqual(entries, [])
        self.assertIn("503", err)
        self.assertEqual(mock_req.call_count, jobber.MAX_ATTEMPTS)


def _fake_config(values):
    return lambda key, default=None: values.get(key, default)


def _response(status, body=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.content = b"x" if body is not None else b""
    resp.json.return_value = body
    resp.text = str(body)
    resp.headers = headers or {}
    return resp


@patch("jobber_app.work_hours.hub_client.time.sleep")
@patch("jobber_app.work_hours.hub_client.requests.post")
@patch(
    "jobber_app.work_hours.hub_client.config",
    side_effect=_fake_config({"HUB_BASE_URL": "https://hub.example/", "HUB_INTERNAL_SECRET": "s3cret"}),
)
class WorkHoursHubClientTests(SimpleTestCase):
    rows = [{"jobber_user_id": U1, "date": "2026-10-20", "regular_hours": "7.50",
             "drive_time_hours": "1.25", "source": "jobber"}]

    def test_posts_entries_with_secret_header(self, _cfg, mock_post, mock_sleep):
        mock_post.return_value = _response(200, {"saved": 1, "skipped": 0, "skipped_ids": [], "invalid": []})
        out = hub_client.upsert_work_hours(self.rows)
        self.assertEqual(out["saved"], 1)
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://hub.example/api/internal/work-hours/upsert/")
        self.assertEqual(kwargs["json"], {"entries": self.rows})
        self.assertEqual(kwargs["headers"]["X-Internal-Secret"], "s3cret")

    def test_retries_on_5xx_and_honours_retry_after(self, _cfg, mock_post, mock_sleep):
        mock_post.side_effect = [
            _response(503, {"detail": "down"}),
            _response(429, {"detail": "slow down"}, {"Retry-After": "7"}),
            _response(200, {"saved": 1}),
        ]
        self.assertEqual(hub_client.upsert_work_hours(self.rows)["saved"], 1)
        self.assertEqual([c.args[0] for c in mock_sleep.call_args_list], [2, 7])

    def test_wrong_secret_401_is_not_retried(self, _cfg, mock_post, mock_sleep):
        mock_post.return_value = _response(401, {"detail": "bad secret"})
        with self.assertRaisesMessage(hub_client.HubWorkHoursError, "check HUB_INTERNAL_SECRET"):
            hub_client.upsert_work_hours(self.rows)
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    def test_503_gives_up_after_max_attempts(self, _cfg, mock_post, mock_sleep):
        mock_post.return_value = _response(503, {"detail": "secret not configured"})
        with self.assertRaises(hub_client.HubWorkHoursError) as ctx:
            hub_client.upsert_work_hours(self.rows)
        msg = str(ctx.exception)
        self.assertIn(f"giving up after {hub_client.MAX_ATTEMPTS} attempts", msg)
        self.assertIn("Hub may not have its internal secret configured", msg)
        self.assertEqual(mock_post.call_count, hub_client.MAX_ATTEMPTS)
        self.assertEqual(mock_sleep.call_count, hub_client.MAX_ATTEMPTS - 1)

    def test_missing_secret_raises_without_calling(self, mock_cfg, mock_post, mock_sleep):
        mock_cfg.side_effect = _fake_config({"HUB_BASE_URL": "https://hub.example"})
        with self.assertRaisesMessage(hub_client.HubWorkHoursError, "HUB_INTERNAL_SECRET"):
            hub_client.upsert_work_hours(self.rows)
        mock_post.assert_not_called()


# 2026-10-22 08:00 Toronto → window 2026-10-08 .. 2026-10-21 (14 days ending yesterday).
NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
HUB_OK = {"saved": 0, "skipped": 0, "skipped_ids": [], "invalid": []}


@patch("jobber_app.work_hours.sync.config", side_effect=_fake_config({}))
@patch("jobber_app.work_hours.sync.hub_client.upsert_work_hours")
@patch("jobber_app.work_hours.sync.jobber.fetch_time_sheet_entries")
class WorkHoursSyncTests(TestCase):
    def _entries(self):
        return [
            _entry(U1, datetime(2026, 10, 20, 9), datetime(2026, 10, 20, 16, 30)),
            _entry(U1, datetime(2026, 10, 20, 16, 30), datetime(2026, 10, 20, 17, 45), "DRIVING"),
            _entry(U2, datetime(2026, 10, 21, 8), datetime(2026, 10, 21, 12)),
        ]

    def test_sends_rows_and_records_them(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = (self._entries(), None)
        mock_upsert.return_value = {**HUB_OK, "saved": 2}
        out = sync_work_hours(now=NOW)

        self.assertTrue(out["ok"], out)
        self.assertEqual((out["window_start"], out["window_end_exclusive"]), ("2026-10-08", "2026-10-22"))
        after, before = mock_fetch.call_args.args
        self.assertEqual(after, datetime(2026, 10, 7, 4, tzinfo=timezone.utc))
        self.assertEqual(before, datetime(2026, 10, 22, 4, tzinfo=timezone.utc))
        sent = mock_upsert.call_args.args[0]
        self.assertEqual(sent, [
            {"jobber_user_id": U1, "date": "2026-10-20", "regular_hours": "7.50",
             "drive_time_hours": "1.25", "source": "jobber"},
            {"jobber_user_id": U2, "date": "2026-10-21", "regular_hours": "4.00",
             "drive_time_hours": "0.00", "source": "jobber"},
        ])
        rec = WorkHoursSentDay.objects.get(jobber_user_id=U1, date=date(2026, 10, 20))
        self.assertEqual((rec.regular_hours, rec.drive_time_hours), (Decimal("7.50"), Decimal("1.25")))

    def test_deleted_day_is_resent_as_zero_once(self, mock_fetch, mock_upsert, _cfg):
        WorkHoursSentDay.objects.create(jobber_user_id=U2, date=date(2026, 10, 15), regular_hours=Decimal("6.00"))
        WorkHoursSentDay.objects.create(jobber_user_id=U2, date=date(2026, 10, 1), regular_hours=Decimal("5.00"))
        mock_fetch.return_value = ([], None)
        mock_upsert.return_value = HUB_OK

        out = sync_work_hours(now=NOW)
        self.assertEqual(out["zeroed_days"], 1)
        self.assertEqual(mock_upsert.call_args.args[0], [
            {"jobber_user_id": U2, "date": "2026-10-15", "regular_hours": "0.00",
             "drive_time_hours": "0.00", "source": "jobber"},
        ])
        rec = WorkHoursSentDay.objects.get(jobber_user_id=U2, date=date(2026, 10, 15))
        self.assertEqual(rec.regular_hours, Decimal("0.00"))

        mock_upsert.reset_mock()
        out = sync_work_hours(now=NOW)
        self.assertEqual(out["zeroed_days"], 0)
        mock_upsert.assert_not_called()

    def test_jobber_failure_sends_nothing(self, mock_fetch, mock_upsert, _cfg):
        WorkHoursSentDay.objects.create(jobber_user_id=U2, date=date(2026, 10, 15), regular_hours=Decimal("6.00"))
        mock_fetch.return_value = ([], "Jobber API HTTP 503: unavailable")
        out = sync_work_hours(now=NOW)
        self.assertFalse(out["ok"])
        self.assertIn("503", out["error"])
        mock_upsert.assert_not_called()
        self.assertEqual(
            WorkHoursSentDay.objects.get(jobber_user_id=U2, date=date(2026, 10, 15)).regular_hours,
            Decimal("6.00"),
        )

    def test_invalid_rows_are_not_recorded_and_skipped_are_logged(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = (self._entries(), None)
        mock_upsert.return_value = {"saved": 0, "skipped": 1, "skipped_ids": [U2],
                                    "invalid": [{"index": 0, "errors": ["bad"]}]}
        with self.assertLogs("jobber_app.work_hours.sync", level="WARNING") as logs:
            out = sync_work_hours(now=NOW)
        self.assertEqual((out["skipped"], out["skipped_users"], out["invalid"]), (1, [U2], 1))
        self.assertTrue(any("1 work-hours rows for 1 unknown" in line and U2 in line for line in logs.output))
        self.assertFalse(WorkHoursSentDay.objects.filter(jobber_user_id=U1).exists())
        self.assertTrue(WorkHoursSentDay.objects.filter(jobber_user_id=U2).exists())

    def test_batches_requests(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = (self._entries() + [
            _entry(U2, datetime(2026, 10, 19, 8), datetime(2026, 10, 19, 9)),
        ], None)
        mock_upsert.return_value = {**HUB_OK, "saved": 1}
        with patch("jobber_app.work_hours.sync.BATCH_SIZE", 2):
            out = sync_work_hours(now=NOW)
        self.assertEqual([len(c.args[0]) for c in mock_upsert.call_args_list], [2, 1])
        self.assertEqual(out["saved"], 2)

    def test_hub_failure_reports_error(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = (self._entries(), None)
        mock_upsert.side_effect = hub_client.HubWorkHoursError("Hub HTTP 401: bad secret")
        out = sync_work_hours(now=NOW)
        self.assertFalse(out["ok"])
        self.assertIn("401", out["error"])
        self.assertFalse(WorkHoursSentDay.objects.exists())

    def test_dry_run_does_not_call_hub_or_write(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = (self._entries(), None)
        out = sync_work_hours(now=NOW, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertEqual(out["days_to_send"], 2)
        self.assertEqual(len(out["sample"]), 2)
        mock_upsert.assert_not_called()
        self.assertFalse(WorkHoursSentDay.objects.exists())

    def test_day_over_24_hours_is_capped(self, mock_fetch, mock_upsert, _cfg):
        mock_fetch.return_value = ([
            _entry(U1, datetime(2026, 10, 20, 0), datetime(2026, 10, 20, 20)),
            _entry(U1, datetime(2026, 10, 20, 8), datetime(2026, 10, 20, 16)),
        ], None)
        mock_upsert.return_value = HUB_OK
        with self.assertLogs("jobber_app.work_hours.sync", level="WARNING"):
            sync_work_hours(now=NOW)
        self.assertEqual(mock_upsert.call_args.args[0][0]["regular_hours"], "24.00")
