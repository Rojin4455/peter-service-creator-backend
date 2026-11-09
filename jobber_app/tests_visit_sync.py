from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from jobber_app.models import VisitSyncState
from jobber_app.visit_sync import jobber
from jobber_app.visit_sync.amounts import allocate, build_entry, deleted_entry
from jobber_app.visit_sync.sync import UPSERT_PATH, sync_visits
from jobber_app.work_hours import hub_client

TORONTO = ZoneInfo("America/Toronto")
U1 = "Z2lkOi8vSm9iYmVyL1VzZXIvMQ=="


def _visit(vid, start="2026-10-20T14:00:00Z", status="COMPLETED", lines=(229.0,), billing="VISIT_BASED",
           freq="PER_VISIT", client="Jane Doe", invoice=None, assigned=(U1,)):
    """invoice: dict(id, subtotal, discount, tips, count) or None."""
    visit = {
        "id": vid,
        "startAt": start,
        "visitStatus": status,
        "completedAt": "2026-10-20T17:00:00Z" if status == "COMPLETED" else None,
        "assignedUsers": {"nodes": [{"id": a} for a in assigned]},
        "lineItems": {"nodes": [{"totalPrice": p} for p in lines]},
        "client": {"id": "C1", "name": client},
        "job": {"id": "J1", "jobNumber": 3389, "title": "Monthly Cleaning", "billingType": billing,
                "invoiceSchedule": {"billingFrequency": freq}},
        "invoice": None,
    }
    if invoice:
        visit["invoice"] = {
            "id": invoice["id"],
            "amounts": {"subtotal": invoice["subtotal"], "discountAmount": invoice.get("discount", 0),
                        "tipsTotal": invoice.get("tips", 0)},
            "visits": {"totalCount": invoice["count"]},
        }
    return visit


class VisitAmountsTests(SimpleTestCase):
    def test_allocate_is_proportional_and_sums_exactly(self):
        self.assertEqual(
            allocate(Decimal("100"), {"a": 1, "b": 1, "c": 1}),
            {"a": Decimal("33.34"), "b": Decimal("33.33"), "c": Decimal("33.33")},
        )
        shares = allocate(Decimal("4880.00"), {"a": 6480, "b": 6480, "c": 3240})
        self.assertEqual(shares, {"a": Decimal("1952.00"), "b": Decimal("1952.00"), "c": Decimal("976.00")})
        self.assertEqual(sum(allocate(Decimal("10.01"), {"a": 1, "b": 2, "c": 4}).values()), Decimal("10.01"))

    def test_allocate_equal_split_when_weights_missing_or_zero(self):
        self.assertEqual(allocate(Decimal("90"), {"a": 0, "b": None, "c": 0}),
                         {"a": Decimal("30.00"), "b": Decimal("30.00"), "c": Decimal("30.00")})

    def test_allocate_negative_total(self):
        self.assertEqual(allocate(Decimal("-1.00"), {"a": 1, "b": 1}), {"a": Decimal("-0.50"), "b": Decimal("-0.50")})

    def test_not_invoiced_is_estimate_from_line_items(self):
        e = build_entry(_visit("V1"), TORONTO)
        self.assertEqual((e["amount_rule"], e["amount_is_estimate"], e["amount_needs_review"]), ("estimate", True, False))
        self.assertEqual((e["visit_amount"], e["line_items_total"], e["discount_share"]), ("229.00", "229.00", "0.00"))
        self.assertIsNone(e["invoice_id"])

    def test_never_invoice_job_uses_job_price(self):
        e = build_entry(_visit("V1", freq="NEVER", lines=(280.0,)), TORONTO)
        self.assertEqual(
            (e["amount_rule"], e["visit_amount"], e["amount_is_estimate"], e["amount_needs_review"]),
            ("job_price", "280.00", False, False),
        )

    def test_never_invoice_zero_or_fixed_price_still_needs_review(self):
        e = build_entry(_visit("V1", freq="NEVER", lines=(0,), client="Vivier Pharma Inc."), TORONTO)
        self.assertEqual((e["amount_rule"], e["amount_needs_review"]), ("job_price", True))
        e = build_entry(_visit("V1", freq="NEVER", billing="FIXED_PRICE"), TORONTO)
        self.assertEqual((e["amount_rule"], e["amount_needs_review"]), ("job_price", True))

    def test_never_invoice_job_with_an_invoice_uses_the_invoice(self):
        e = build_entry(_visit("V1", freq="NEVER", invoice={"id": "I1", "subtotal": 250.0, "count": 1}), TORONTO)
        self.assertEqual((e["amount_rule"], e["visit_amount"]), ("invoice", "250.00"))

    def test_fixed_price_estimate_needs_review(self):
        self.assertTrue(build_entry(_visit("V1", billing="FIXED_PRICE", freq="PERIODIC"), TORONTO)["amount_needs_review"])

    def test_single_visit_invoice_uses_invoice_amounts(self):
        e = build_entry(_visit("V1", invoice={"id": "I1", "subtotal": 129.0, "discount": 10, "tips": 15.9, "count": 1}),
                        TORONTO)
        self.assertEqual(e["amount_rule"], "invoice")
        self.assertFalse(e["amount_is_estimate"])
        self.assertEqual((e["visit_amount"], e["discount_share"], e["tip_share"]), ("129.00", "10.00", "15.90"))
        self.assertEqual((e["line_items_total"], e["invoice_subtotal"], e["invoice_id"]), ("229.00", "129.00", "I1"))

    def test_multi_visit_invoice_split_by_line_price(self):
        inv = {"id": "I1", "subtotal": 4880.0, "discount": 100, "tips": 0.03, "count": 3}
        weights = {"V1": Decimal("6480"), "V2": Decimal("6480"), "V3": Decimal("3240")}
        rows = [build_entry(_visit(v, lines=(6480.0,), invoice=inv), TORONTO, weights) for v in ("V1", "V2", "V3")]
        self.assertEqual({r["amount_rule"] for r in rows}, {"invoice_share"})
        self.assertEqual(rows[0]["visit_amount"], "1952.00")
        self.assertEqual(sum(Decimal(r["visit_amount"]) for r in rows), Decimal("4880.00"))
        self.assertEqual(sum(Decimal(r["discount_share"]) for r in rows), Decimal("100.00"))
        self.assertEqual(sum(Decimal(r["tip_share"]) for r in rows), Decimal("0.03"))

    def test_multi_visit_invoice_without_weights_needs_review(self):
        e = build_entry(_visit("V1", invoice={"id": "I1", "subtotal": 500, "count": 2}), TORONTO, None)
        self.assertEqual((e["amount_rule"], e["amount_is_estimate"], e["amount_needs_review"]), ("estimate", True, True))
        self.assertEqual((e["invoice_id"], e["invoice_subtotal"], e["visit_amount"]), ("I1", "500.00", "229.00"))

    def test_internal_visit_is_zero(self):
        e = build_entry(_visit("V1", client="CLEAN ON THE GO INC.", lines=(0,), freq="NEVER"), TORONTO)
        self.assertTrue(e["internal"])
        self.assertFalse(e["amount_needs_review"])
        self.assertEqual((e["visit_amount"], e["tip_share"]), ("0.00", "0.00"))

    def test_entry_shape_and_toronto_date(self):
        e = build_entry(_visit("V1", start="2026-10-21T02:00:00Z"), TORONTO)
        self.assertEqual(e["date"], "2026-10-20")
        self.assertEqual(
            set(e),
            {"jobber_visit_id", "jobber_job_id", "job_number", "job_title", "client_jobber_id", "client_name",
             "date", "status", "completed_at", "assigned_user_ids", "visit_amount", "discount_share", "tip_share",
             "line_items_total", "invoice_id", "invoice_subtotal", "invoice_discount", "invoice_tips",
             "amount_rule", "amount_is_estimate", "amount_needs_review", "internal"},
        )
        self.assertEqual(e["assigned_user_ids"], [U1])
        self.assertIsNone(build_entry(_visit("V2", start=None, status="UNSCHEDULED"), TORONTO)["date"])

    def test_deleted_entry_zeroes_amounts(self):
        last = build_entry(_visit("V1", invoice={"id": "I1", "subtotal": 129.0, "count": 1}), TORONTO)
        e = deleted_entry("V1", last)
        self.assertEqual(e["status"], "deleted")
        self.assertEqual((e["visit_amount"], e["invoice_subtotal"], e["line_items_total"]), ("0.00", "0.00", "0.00"))
        self.assertIsNone(e["invoice_id"])
        self.assertEqual((e["jobber_visit_id"], e["client_name"]), ("V1", "Jane Doe"))
        self.assertEqual(deleted_entry("V2", {})["jobber_visit_id"], "V2")

    def test_implausible_per_visit_invoice_split_needs_review(self):
        # Real case: one 215.00 invoice linked to 43 visits of a ~229.00 job.
        inv = {"id": "I1", "subtotal": 215.0, "count": 43}
        weights = {f"V{i}": Decimal("229") for i in range(43)}
        e = build_entry(_visit("V0", invoice=inv), TORONTO, weights)
        self.assertEqual((e["amount_rule"], e["visit_amount"], e["amount_needs_review"]), ("invoice_share", "5.00", True))

    def test_plausible_splits_are_not_flagged(self):
        # Monthly per-visit invoice: 4 × 349 billed as 1,396; fixed-price Globe split far below its line sum.
        weights = {f"V{i}": Decimal("349") for i in range(4)}
        e = build_entry(_visit("V0", lines=(349,), invoice={"id": "I1", "subtotal": 1396, "count": 4}), TORONTO, weights)
        self.assertEqual((e["visit_amount"], e["amount_needs_review"]), ("349.00", False))
        globe = {f"V{i}": Decimal("6480") for i in range(12)}
        e = build_entry(_visit("V0", lines=(6480,), billing="FIXED_PRICE", freq="PERIODIC",
                               invoice={"id": "I2", "subtotal": 6480, "count": 12}), TORONTO, globe)
        self.assertEqual((e["visit_amount"], e["amount_needs_review"]), ("540.00", False))

    def test_unpriced_visit_on_shared_invoice_needs_review(self):
        weights = {"V1": Decimal("0"), "V2": Decimal("200")}
        e = build_entry(_visit("V1", lines=(), invoice={"id": "I1", "subtotal": 200, "count": 2}), TORONTO, weights)
        self.assertEqual((e["visit_amount"], e["amount_needs_review"]), ("0.00", True))


@patch("jobber_app.visit_sync.jobber._request_with_backoff")
class VisitJobberFetchTests(SimpleTestCase):
    @patch("jobber_app.visit_sync.jobber.time.sleep")
    def test_window_visits_paginate_with_inline_filter(self, mock_sleep, mock_req):
        mock_req.side_effect = [
            ({"visits": {"nodes": [{"id": "V1"}], "pageInfo": {"hasNextPage": True, "endCursor": "c1"}}}, None),
            ({"visits": {"nodes": [{"id": "V2"}], "pageInfo": {"hasNextPage": False}}}, None),
        ]
        out = jobber.fetch_window_visits(datetime(2026, 10, 3, 4, tzinfo=timezone.utc),
                                         datetime(2026, 11, 3, 4, tzinfo=timezone.utc))
        self.assertEqual([v["id"] for v in out], ["V1", "V2"])
        query, variables = mock_req.call_args_list[0].args
        self.assertIn('startAt: { after: "2026-10-03T04:00:00+00:00"', query)
        self.assertNotIn("after", variables)
        self.assertEqual(mock_req.call_args_list[1].args[1]["after"], "c1")

    def test_fetch_visit_not_found_means_deleted(self, mock_req):
        mock_req.return_value = (None, "Visit not found")
        self.assertIsNone(jobber.fetch_visit("V1"))
        mock_req.return_value = ({"visit": None}, None)
        self.assertIsNone(jobber.fetch_visit("V1"))

    def test_fetch_visit_other_error_raises(self, mock_req):
        mock_req.return_value = (None, "Jobber API HTTP 503: unavailable")
        with self.assertRaises(jobber.JobberFetchError):
            jobber.fetch_visit("V1")

    def test_invoice_weights_incomplete_returns_none(self, mock_req):
        mock_req.return_value = ({"invoice": {"visits": {"totalCount": 3, "nodes": [
            {"id": "V1", "lineItems": {"nodes": [{"totalPrice": 10}]}}]}}}, None)
        self.assertIsNone(jobber.fetch_invoice_line_weights("I1"))
        mock_req.return_value = ({"invoice": {"visits": {"totalCount": 2, "nodes": [
            {"id": "V1", "lineItems": {"nodes": [{"totalPrice": 10}, {"totalPrice": 5}]}},
            {"id": "V2", "lineItems": {"nodes": []}}]}}}, None)
        self.assertEqual(jobber.fetch_invoice_line_weights("I1"), {"V1": Decimal("15"), "V2": 0})


def _config(enabled):
    values = {"VISITS_SYNC_ENABLED": enabled}
    return lambda key, default=None, cast=None: values.get(key, default)


# Toronto 2026-11-03 → window 2026-10-04 .. 2026-12-15 inclusive (30 back, 42 forward).
NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
HUB_OK = {"saved": 0, "invalid": []}


@patch("jobber_app.visit_sync.sync.hub_client.upsert_entries")
@patch("jobber_app.visit_sync.sync.jobber")
class VisitSyncTests(TestCase):
    def _setup(self, mock_jobber, window=(), updated=(), by_id=None, weights=None):
        mock_jobber.JobberFetchError = jobber.JobberFetchError
        mock_jobber.fetch_window_visits.return_value = list(window)
        mock_jobber.fetch_updated_invoice_visit_ids.return_value = list(updated)
        mock_jobber.fetch_visit.side_effect = lambda vid: (by_id or {}).get(vid)
        mock_jobber.fetch_invoice_line_weights.side_effect = lambda iid: (weights or {}).get(iid)

    def test_disabled_sends_nothing(self, mock_jobber, mock_upsert):
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(False)):
            out = sync_visits(now=NOW)
        self.assertTrue(out["ok"])
        self.assertIn("VISITS_SYNC_ENABLED", out["skipped"])
        mock_jobber.fetch_window_visits.assert_not_called()
        mock_upsert.assert_not_called()

    def test_dry_run_works_while_disabled_without_writes(self, mock_jobber, mock_upsert):
        self._setup(mock_jobber, window=[_visit("V1")])
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(False)):
            out = sync_visits(now=NOW, dry_run=True)
        self.assertTrue(out["ok"])
        self.assertEqual((out["visits"], out["by_amount_rule"]["estimate"]), (1, 1))
        mock_upsert.assert_not_called()
        self.assertFalse(VisitSyncState.objects.exists())

    def test_sends_window_and_updated_invoice_visits_and_records_them(self, mock_jobber, mock_upsert):
        old = _visit("V0", start="2026-09-15T14:00:00Z", invoice={"id": "I0", "subtotal": 99, "tips": 5, "count": 1})
        upcoming = _visit("VUP", start="2026-12-10T15:00:00Z", status="UPCOMING")
        self._setup(mock_jobber, window=[_visit("V1"), upcoming], updated=["V1", "V0"], by_id={"V0": old})
        mock_upsert.return_value = {"saved": 3, "invalid": []}
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        self.assertTrue(out["ok"], out)
        self.assertEqual((out["window_start"], out["window_end_exclusive"]), ("2026-10-04", "2026-12-16"))
        path, sent = mock_upsert.call_args.args
        self.assertEqual(path, UPSERT_PATH)
        self.assertEqual([e["jobber_visit_id"] for e in sent], ["V0", "V1", "VUP"])
        self.assertEqual(sent[0]["tip_share"], "5.00")
        self.assertEqual(
            (sent[2]["date"], sent[2]["status"], sent[2]["amount_rule"], sent[2]["amount_is_estimate"]),
            ("2026-12-10", "UPCOMING", "estimate", True),
        )
        mock_jobber.fetch_visit.assert_called_once_with("V0")
        self.assertEqual(VisitSyncState.objects.get(jobber_visit_id="V1").date, date(2026, 10, 20))

    def test_deleted_visit_resent_once_but_rescheduled_visit_is_not_deleted(self, mock_jobber, mock_upsert):
        gone = build_entry(_visit("VGONE", invoice={"id": "I1", "subtotal": 200, "count": 1}), TORONTO)
        moved = build_entry(_visit("VMOVED"), TORONTO)
        VisitSyncState.objects.create(jobber_visit_id="VGONE", date=date(2026, 10, 20), status="COMPLETED", payload=gone)
        VisitSyncState.objects.create(jobber_visit_id="VMOVED", date=date(2026, 10, 21), status="UPCOMING", payload=moved)
        VisitSyncState.objects.create(jobber_visit_id="VOLD", date=date(2026, 9, 1), status="COMPLETED", payload={})
        # Rescheduled beyond even the 42-day forward window: updated, not marked deleted.
        self._setup(mock_jobber, window=[], by_id={"VMOVED": _visit("VMOVED", start="2027-01-15T14:00:00Z",
                                                                   status="UPCOMING")})
        mock_upsert.return_value = HUB_OK
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        sent = {e["jobber_visit_id"]: e for e in mock_upsert.call_args.args[1]}
        self.assertEqual(set(sent), {"VGONE", "VMOVED"})
        self.assertEqual((sent["VGONE"]["status"], sent["VGONE"]["visit_amount"]), ("deleted", "0.00"))
        self.assertEqual((sent["VMOVED"]["status"], sent["VMOVED"]["date"]), ("UPCOMING", "2027-01-15"))
        self.assertEqual(out["deleted"], 1)
        self.assertEqual(VisitSyncState.objects.get(jobber_visit_id="VGONE").status, "deleted")

        # Next night: the deleted visit is not re-sent, and the moved visit is now outside the window.
        mock_upsert.reset_mock()
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        self.assertEqual((out["visits"], out["deleted"]), (0, 0))
        mock_upsert.assert_not_called()

    def test_jobber_error_sends_nothing_and_deletes_nothing(self, mock_jobber, mock_upsert):
        VisitSyncState.objects.create(jobber_visit_id="V9", date=date(2026, 10, 20), status="COMPLETED", payload={})
        self._setup(mock_jobber)
        mock_jobber.fetch_window_visits.side_effect = jobber.JobberFetchError("Jobber API HTTP 503")
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        self.assertFalse(out["ok"])
        self.assertIn("503", out["error"])
        mock_upsert.assert_not_called()
        self.assertEqual(VisitSyncState.objects.get(jobber_visit_id="V9").status, "COMPLETED")

    def test_multi_visit_invoice_weights_fetched_once_and_split(self, mock_jobber, mock_upsert):
        inv = {"id": "I1", "subtotal": 300, "count": 2}
        self._setup(mock_jobber, window=[_visit("V1", lines=(100,), invoice=inv), _visit("V2", lines=(200,), invoice=inv)],
                    weights={"I1": {"V1": Decimal("100"), "V2": Decimal("200")}})
        mock_upsert.return_value = HUB_OK
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        mock_jobber.fetch_invoice_line_weights.assert_called_once_with("I1")
        sent = {e["jobber_visit_id"]: e["visit_amount"] for e in mock_upsert.call_args.args[1]}
        self.assertEqual(sent, {"V1": "100.00", "V2": "200.00"})
        self.assertEqual(out["by_amount_rule"]["invoice_share"], 2)

    def test_invalid_rows_not_recorded_and_hub_error_reported(self, mock_jobber, mock_upsert):
        self._setup(mock_jobber, window=[_visit("V1"), _visit("V2")])
        mock_upsert.return_value = {"saved": 1, "unknown_user_ids": [U1, U1],
                                    "invalid": [{"index": 0, "errors": ["bad"]}]}
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        self.assertEqual((out["saved"], out["invalid"], out["unknown_user_ids"]), (1, 1, [U1]))
        self.assertEqual(out["invalid_examples"], [{"index": 0, "errors": ["bad"]}])
        self.assertEqual(list(VisitSyncState.objects.values_list("jobber_visit_id", flat=True)), ["V2"])

        mock_upsert.side_effect = hub_client.HubWorkHoursError("Hub HTTP 404: not found")
        with patch("jobber_app.visit_sync.sync.config", side_effect=_config(True)):
            out = sync_visits(now=NOW)
        self.assertFalse(out["ok"])
        self.assertIn("404", out["error"])
