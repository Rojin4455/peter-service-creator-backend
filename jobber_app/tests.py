from unittest.mock import patch

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

