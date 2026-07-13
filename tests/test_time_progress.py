import unittest
from datetime import datetime

from codex_float_ui import (
    format_reset_text,
    quota_row_is_available,
    snap_position,
    status_is_stale,
    time_remaining_percent,
)


class TimeRemainingPercentTest(unittest.TestCase):
    def test_5h_progress_uses_remaining_time_until_reset(self):
        now = datetime(2026, 6, 18, 12, 0, 0)

        self.assertEqual(time_remaining_percent("2:30 PM", 5 * 60, now), 50)


    def test_5h_progress_represents_remaining_time_not_elapsed_time(self):
        now = datetime(2026, 6, 18, 12, 0, 0)

        self.assertEqual(time_remaining_percent("1:00 PM", 5 * 60, now), 20)

    def test_weekly_progress_uses_remaining_time_until_reset(self):
        now = datetime(2026, 6, 18, 12, 0, 0)

        self.assertEqual(time_remaining_percent("Jun 22 00:00", 7 * 24 * 60, now), 50)

    def test_weekly_progress_parses_codex_time_on_day_month_format(self):
        now = datetime(2026, 6, 21, 22, 4, 0)

        self.assertEqual(time_remaining_percent("10:04 on 25 Jun", 7 * 24 * 60, now), 50)

    def test_unparseable_reset_has_no_progress(self):
        now = datetime(2026, 6, 18, 12, 0, 0)

        self.assertIsNone(time_remaining_percent("N/A", 5 * 60, now))

    def test_weekly_reset_shows_month_day_when_not_today(self):
        now = datetime(2026, 7, 2, 8, 0, 0)

        self.assertEqual(format_reset_text("weekly", "10:53 on 7 Jul", now), "7.7")

    def test_weekly_reset_shows_time_when_today(self):
        now = datetime(2026, 7, 7, 8, 0, 0)

        self.assertEqual(format_reset_text("weekly", "10:53 on 7 Jul", now), "10:53")

    def test_5h_reset_keeps_original_time_text(self):
        now = datetime(2026, 7, 2, 8, 0, 0)

        self.assertEqual(format_reset_text("h5", "13:43", now), "13:43")

    def test_spark_reset_shows_month_day_when_not_today(self):
        now = datetime(2026, 7, 2, 8, 0, 0)

        self.assertEqual(format_reset_text("spark", "10:53 on 7 Jul", now), "7.7")

    def test_spark_reset_shows_time_when_today(self):
        now = datetime(2026, 7, 7, 8, 0, 0)

        self.assertEqual(format_reset_text("spark", "10:53 on 7 Jul", now), "10:53")

    def test_status_is_stale_after_more_than_three_minutes(self):
        now = datetime(2026, 7, 2, 8, 4, 1)

        self.assertTrue(status_is_stale("2026-07-02 08:01:00", now))

    def test_status_is_not_stale_at_three_minutes(self):
        now = datetime(2026, 7, 2, 8, 4, 0)

        self.assertFalse(status_is_stale("2026-07-02 08:01:00", now))

    def test_invalid_status_timestamp_is_stale(self):
        now = datetime(2026, 7, 2, 8, 4, 0)

        self.assertTrue(status_is_stale("bad timestamp", now))

    def test_quota_row_is_hidden_when_left_percent_is_missing(self):
        self.assertFalse(quota_row_is_available(None))

    def test_quota_row_is_visible_when_left_percent_is_zero(self):
        self.assertTrue(quota_row_is_available(0))

    def test_snap_position_snaps_to_top_edge(self):
        self.assertEqual(
            snap_position(120, 10, 200, 80, 1000, 800, 24),
            (120, 0),
        )

    def test_snap_position_snaps_to_right_edge(self):
        self.assertEqual(
            snap_position(785, 120, 200, 80, 1000, 800, 24),
            (800, 120),
        )

    def test_snap_position_keeps_position_outside_threshold(self):
        self.assertEqual(
            snap_position(120, 40, 200, 80, 1000, 800, 24),
            (120, 40),
        )

    def test_snap_position_can_ignore_top_edge_when_dragging_away(self):
        self.assertEqual(
            snap_position(120, 10, 200, 80, 1000, 800, 24, ignored_edges={"top"}),
            (120, 10),
        )


if __name__ == "__main__":
    unittest.main()
