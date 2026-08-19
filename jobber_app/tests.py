from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone
from datetime import timedelta

from jobber_app.lock_in.matching import (
    classify_jobs,
    is_internal_client,
    pick_frequency,
    recurring_frequency_from_title,
    title_is_first_cleaning,
    title_is_lock_in_job,
)
from jobber_app.lock_in import stage2


class LockInMatchingTests(SimpleTestCase):
    def test_internal_client(self):
        self.assertTrue(is_internal_client("CLEAN ON THE GO INC."))
        self.assertTrue(is_internal_client("clean on the go inc."))
        self.assertFalse(is_internal_client("Jane Doe"))

    def test_biweekly_before_weekly(self):
        self.assertEqual(recurring_frequency_from_title("Bi-weekly Recurring"), "Bi-weekly")
        self.assertEqual(recurring_frequency_from_title("Weekly Clean"), "Weekly")
        self.assertEqual(recurring_frequency_from_title("Monthly"), "Monthly")

    def test_classify(self):
        first, rec = classify_jobs(
            [
                {"id": "1", "title": "First Cleaning - Jane"},
                {"id": "2", "title": "Weekly Recurring"},
                {"id": "3", "title": "Window Wash"},
            ]
        )
        self.assertEqual([j["id"] for j in first], ["1"])
        self.assertEqual([j["id"] for j in rec], ["2"])
        self.assertEqual(pick_frequency(rec), "Weekly")

    def test_first_cleaning_flag(self):
        self.assertTrue(title_is_first_cleaning("Residential First Cleaning"))
        self.assertTrue(title_is_lock_in_job("First Cleaning"))
        self.assertFalse(title_is_lock_in_job("Move Out"))


class LockInStage2Tests(SimpleTestCase):
    def test_skips_first_cleaning(self):
        visit = {
            "id": "v1",
            "title": "First Cleaning",
            "client": {"id": "c1", "name": "Jane"},
            "job": {"id": "j1", "jobType": "ONE_OFF"},
        }
        out = stage2.process_visit_complete_confirm(visit)
        self.assertTrue(out["skipped"])
        self.assertEqual(out["reason"], "first_cleaning_visit")

    def test_skips_internal_client(self):
        visit = {
            "id": "v1",
            "title": "Weekly",
            "client": {"id": "c1", "name": "CLEAN ON THE GO INC."},
            "job": {"id": "j1"},
        }
        out = stage2.process_visit_complete_confirm(visit)
        self.assertEqual(out["reason"], "internal_client")

    @patch("jobber_app.lock_in.stage2.hub_client")
    def test_expires_outside_three_months(self, hub):
        hub.lookup_pending.return_value = {
            "pending": {
                "id": "p1",
                "job_id": "jr",
                "locked_in": False,
                "status": "in_process",
                "original_visit_ids": [],
                "eligibility_expires_at": (timezone.now() - timedelta(days=1)).isoformat(),
            }
        }
        visit = {
            "id": "rv1",
            "title": "Weekly Recurring",
            "startAt": timezone.now().isoformat(),
            "client": {"id": "c1", "name": "Jane"},
            "job": {"id": "jr", "jobType": "RECURRING"},
        }
        out = stage2.process_visit_complete_confirm(visit)
        self.assertTrue(out.get("expired"))
        hub.expire_pending.assert_called_once_with("p1")
        hub.confirm_pending.assert_not_called()


def _feedback_visit(**kwargs):
    visit = {
        "id": "v-fb-1",
        "title": "Weekly",
        "client": {
            "id": "c1",
            "name": "Jane Doe",
            "emails": [{"address": "jane@example.com"}],
            "phones": [{"number": "+15555550100"}],
        },
    }
    visit.update(kwargs)
    return visit


class VisitCompleteGhlFeedbackTests(SimpleTestCase):
    def test_skips_internal_client(self):
        from jobber_app.visit_complete_ghl import process_visit_complete_ghl_feedback

        visit = _feedback_visit(client={"id": "c1", "name": "CLEAN ON THE GO INC."})
        qs = MagicMock()
        qs.exists.return_value = False
        with patch(
            "jobber_app.visit_complete_ghl.get_visit_for_ghl_feedback",
            return_value=(visit, None),
        ), patch(
            "jobber_app.visit_complete_ghl.JobberVisitCompletedGhlTrigger.objects"
        ) as objects:
            objects.filter.return_value = qs
            out = process_visit_complete_ghl_feedback("v-fb-1")
        self.assertTrue(out["ok"])
        self.assertEqual(out["reason"], "internal_client")
        objects.create.assert_not_called()

    def test_missing_ghl_contact_is_success(self):
        from jobber_app.visit_complete_ghl import process_visit_complete_ghl_feedback

        qs = MagicMock()
        qs.exists.return_value = False
        row = MagicMock()
        with patch(
            "jobber_app.visit_complete_ghl.get_visit_for_ghl_feedback",
            return_value=(_feedback_visit(), None),
        ), patch(
            "jobber_app.visit_complete_ghl._resolve_location_id",
            return_value=("wpToBiFJKYFBp5hk2bMt", None),
        ), patch(
            "jobber_app.visit_complete_ghl._resolve_ghl_contact",
            return_value=(None, None),
        ), patch(
            "jobber_app.visit_complete_ghl.JobberVisitCompletedGhlTrigger.objects"
        ) as objects:
            objects.filter.return_value = qs
            objects.create.return_value = row
            out = process_visit_complete_ghl_feedback("v-fb-missing")
        self.assertTrue(out["ok"])
        self.assertEqual(out["reason"], "ghl_contact_not_found")
        row.delete.assert_called_once()

    def test_sets_visit_completed_and_is_idempotent(self):
        from jobber_app.visit_complete_ghl import process_visit_complete_ghl_feedback

        qs_empty = MagicMock()
        qs_empty.exists.return_value = False
        qs_done = MagicMock()
        qs_done.exists.return_value = True
        row = MagicMock()
        with patch(
            "jobber_app.visit_complete_ghl.get_visit_for_ghl_feedback",
            return_value=(_feedback_visit(), None),
        ), patch(
            "jobber_app.visit_complete_ghl._resolve_location_id",
            return_value=("wpToBiFJKYFBp5hk2bMt", None),
        ), patch(
            "jobber_app.visit_complete_ghl._resolve_ghl_contact",
            return_value=("ghl-1", None),
        ), patch(
            "jobber_app.visit_complete_ghl.update_contact_custom_fields",
            return_value=(True, None),
        ) as upd, patch(
            "jobber_app.visit_complete_ghl.JobberVisitCompletedGhlTrigger.objects"
        ) as objects:
            objects.filter.side_effect = [qs_empty, qs_done]
            objects.create.return_value = row
            first = process_visit_complete_ghl_feedback("v-fb-dup")
            second = process_visit_complete_ghl_feedback("v-fb-dup")
        self.assertTrue(first["ok"])
        self.assertEqual(first["ghl_contact_id"], "ghl-1")
        self.assertTrue(second["skipped"])
        self.assertEqual(second["reason"], "already_processed")
        self.assertEqual(upd.call_count, 1)
        row.save.assert_called_once()
        args, _kwargs = upd.call_args
        self.assertEqual(args[0], "ghl-1")
        self.assertEqual(args[1][0]["id"], "nX55NHpRyzOnQkkvdHOK")
        self.assertEqual(args[1][0]["field_value"], "yes")

