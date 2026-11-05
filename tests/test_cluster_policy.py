import unittest

from app.core.errors import AppError
from app.service.settings.cluster_policy import apply_cluster_policy, request_timeout, retry_count
from app.service.settings.defaults import default_payload
from app.service.settings.settings_service import SettingsService


class ClusterPolicyTest(unittest.TestCase):
    def test_timeout_stays_within_caps(self):
        apply_cluster_policy({"cluster": {"timeout_s": 8, "retries": 2}})
        self.assertEqual(request_timeout(), 8)
        self.assertEqual(request_timeout(slot=True), 4)
        apply_cluster_policy({"cluster": {"timeout_s": 3, "retries": 2}})
        self.assertEqual(request_timeout(slot=True), 3)

    def test_retries_cap_at_five(self):
        apply_cluster_policy({"cluster": {"timeout_s": 5, "retries": 9}})
        self.assertEqual(retry_count(), 5)

    def test_save_rejects_values_over_the_limit(self):
        body = default_payload()
        body["cluster"]["timeout_s"] = 9
        with self.assertRaises(AppError):
            SettingsService._validate(None, body)
        body = default_payload()
        body["cluster"]["retries"] = 6
        with self.assertRaises(AppError):
            SettingsService._validate(None, body)


if __name__ == "__main__":
    unittest.main()
