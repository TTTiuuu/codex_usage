import json
import tempfile
import unittest
from pathlib import Path

from codex_status_ready import status_json_has_quota_values


class StatusReadyTest(unittest.TestCase):
    def write_status(self, payload):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)

        path = Path(temp_dir.name) / "codex_status.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_missing_file_is_not_ready(self):
        self.assertFalse(status_json_has_quota_values("/tmp/does-not-exist.json"))

    def test_status_with_no_quota_values_is_not_ready(self):
        path = self.write_status({
            "status": {
                "limit_5h_left_percent": None,
                "weekly_left_percent": None,
            }
        })

        self.assertFalse(status_json_has_quota_values(path))

    def test_status_with_quota_values_is_ready(self):
        path = self.write_status({
            "status": {
                "limit_5h_left_percent": 42,
                "weekly_left_percent": 80,
            }
        })

        self.assertTrue(status_json_has_quota_values(path))

    def test_status_with_weekly_only_is_ready(self):
        path = self.write_status({
            "status": {
                "limit_5h_left_percent": None,
                "weekly_left_percent": 100,
            }
        })

        self.assertTrue(status_json_has_quota_values(path))

    def test_status_with_spark_only_is_ready(self):
        path = self.write_status({
            "status": {
                "weekly_left_percent": None,
                "spark_weekly_left_percent": 100,
            }
        })

        self.assertTrue(status_json_has_quota_values(path))

    def test_status_with_error_is_not_ready(self):
        path = self.write_status({
            "error": "tmux failed",
            "status": {"weekly_left_percent": 95},
        })

        self.assertFalse(status_json_has_quota_values(path))


if __name__ == "__main__":
    unittest.main()
