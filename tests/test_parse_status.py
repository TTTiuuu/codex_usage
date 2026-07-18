import json
import os
import tempfile
import unittest

from codex_tmux_status_watch import (
    parse_status,
    status_has_displayable_quota,
    status_needs_limit_refresh,
    write_error_status,
    write_json,
)


class ParseStatusTest(unittest.TestCase):
    def test_keeps_primary_limits_when_pro_status_includes_spark_limits(self):
        text = """
│  Account:                     rareay.tan@gmail.com (Plus)                    │
│                                                                              │
│  5h limit:                    [█████████████████░░░] 86% left (resets 20:53) │
│  Weekly limit:                [██████████████████░░] 92% left                │
│                               (resets 10:53 on 7 Jul)                        │
│  GPT-5.3-Codex-Spark limit:                                                  │
│  5h limit:                    [████████████████████] 100% left               │
│                               (resets 22:06)                                 │
│  Weekly limit:                [████████████████████] 100% left               │
│                               (resets 17:06 on 7 Jul)                        │
"""

        status = parse_status(text)

        self.assertEqual(status["limit_5h_left_percent"], 86)
        self.assertEqual(status["limit_5h_reset"], "20:53")
        self.assertEqual(status["weekly_left_percent"], 92)
        self.assertEqual(status["weekly_reset"], "10:53 on 7 Jul")
        self.assertEqual(status["spark_weekly_left_percent"], 100)
        self.assertEqual(status["spark_weekly_reset"], "17:06 on 7 Jul")

    def test_parses_spark_weekly_on_single_line(self):
        """用户实际的 /status 输出格式：GPT-5.3-Codex-Spark Weekly limit 在同一行"""
        text = """
│  Weekly limit:                       [███████████████████░] 95% left (resets 09:17 on 20 Jul)  │
│  GPT-5.3-Codex-Spark Weekly limit:   [████████████████████] 100% left (resets 18:19 on 20 Jul) │
"""

        status = parse_status(text)

        self.assertEqual(status["weekly_left_percent"], 95)
        self.assertEqual(status["weekly_reset"], "09:17 on 20 Jul")
        self.assertEqual(status["spark_weekly_left_percent"], 100)
        self.assertEqual(status["spark_weekly_reset"], "18:19 on 20 Jul")

    def test_primary_weekly_is_not_lost_when_it_follows_spark(self):
        text = """
│ GPT-5.3-Codex-Spark Weekly limit: 100% left (resets 18:19 on 20 Jul) │
│ Weekly limit: 95% left (resets 09:17 on 20 Jul) │
"""

        status = parse_status(text)

        self.assertEqual(status["spark_weekly_left_percent"], 100)
        self.assertEqual(status["weekly_left_percent"], 95)

    def test_rejects_out_of_range_percentage(self):
        status = parse_status("Weekly limit: 101% left (resets 09:17 on 20 Jul)")

        self.assertIsNone(status["weekly_left_percent"])
        self.assertFalse(status_has_displayable_quota(status))

    def test_write_json_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "status.json")
            write_json(path, {"status": {}})

            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_error_status_preserves_last_good_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "status.json")
            write_json(
                path,
                {
                    "timestamp": "2026-07-18 12:00:00",
                    "last_success_at": "2026-07-18 12:00:00",
                    "error": "",
                    "status": {"weekly_left_percent": 95},
                },
            )

            write_error_status(
                path,
                "tmux failed",
                "2026-07-18 12:01:00",
                "/tmp/work",
                "quota",
            )

            with open(path, encoding="utf-8") as f:
                result = json.load(f)
            self.assertEqual(result["last_success_at"], "2026-07-18 12:00:00")
            self.assertEqual(result["status"]["weekly_left_percent"], 95)
            self.assertEqual(result["error"], "tmux failed")

    def test_detects_status_limit_refresh_request(self):
        text = """
│  Limits:               refresh requested; run /status again shortly. │
"""

        self.assertTrue(status_needs_limit_refresh(text))

    def test_real_limits_do_not_need_refresh(self):
        text = """
│  5h limit:                    [████████████████████] 100% left           │
│                               (resets 13:43)                             │
│  Weekly limit:                [████████████░░░░░░░░] 58% left            │
│                               (resets 10:53 on 7 Jul)                    │
"""

        self.assertFalse(status_needs_limit_refresh(text))


if __name__ == "__main__":
    unittest.main()
