import unittest
from unittest.mock import patch

from codex_float_ui import BAR_WIDTH, CodexFloatingUI, SEG_GAP


class FakeCanvas:
    def __init__(self):
        self.rectangles = []

    def delete(self, _target):
        self.rectangles.clear()

    def winfo_width(self):
        return BAR_WIDTH

    def create_rectangle(self, x0, y0, x1, y1, **options):
        self.rectangles.append((x0, y0, x1, y1, options))

    def create_line(self, *_args, **_kwargs):
        pass


class FakeLabel:
    def __init__(self):
        self.options = {}

    def config(self, **options):
        self.options.update(options)


class ImmediateRoot:
    def after(self, _delay, callback):
        callback()


class UIRenderingTest(unittest.TestCase):
    def make_ui(self):
        ui = CodexFloatingUI.__new__(CodexFloatingUI)
        ui.root = ImmediateRoot()
        ui.weekly_value = FakeLabel()
        ui.weekly_reset = FakeLabel()
        ui.weekly_bar = FakeCanvas()
        ui.weekly_time_bar = FakeCanvas()
        return ui

    def test_segment_fill_preserves_configured_gaps(self):
        ui = self.make_ui()
        ui.draw_weekly_segmented_bar(ui.weekly_bar, 100, 50)

        fills = [
            rect
            for rect in ui.weekly_bar.rectangles
            if rect[4].get("fill") == "#5aa9ff"
        ]
        self.assertEqual(len(fills), 7)
        for previous, current in zip(fills, fills[1:]):
            self.assertAlmostEqual(current[0] - previous[2], SEG_GAP)

    @patch("codex_float_ui.time_remaining_percent", return_value=80)
    def test_value_label_uses_same_quota_vs_time_color_as_bar(self, _time_percent):
        ui = self.make_ui()

        ui.update_section("weekly", 20, "10:00 on 20 Jul")

        self.assertEqual(ui.weekly_value.options["fg"], "#f0b35a")


if __name__ == "__main__":
    unittest.main()
