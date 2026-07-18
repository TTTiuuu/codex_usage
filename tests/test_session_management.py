import unittest
from unittest.mock import patch

from codex_tmux_status_watch import (
    SESSION_COMMAND_OPTION,
    SESSION_MANAGED_OPTION,
    SESSION_WORKDIR_OPTION,
    start_codex_session,
)


class SessionManagementTest(unittest.TestCase):
    @patch("codex_tmux_status_watch.require_cmd")
    @patch("codex_tmux_status_watch.tmux_session_exists", return_value=True)
    @patch("codex_tmux_status_watch.tmux_get_option", return_value="")
    def test_refuses_to_reuse_unmanaged_session(
        self, _get_option, _session_exists, _require_cmd
    ):
        with self.assertRaisesRegex(RuntimeError, "不是本工具创建"):
            start_codex_session("quota", "/tmp", "codex")

    @patch("codex_tmux_status_watch.require_cmd")
    @patch("codex_tmux_status_watch.tmux_session_exists", return_value=True)
    def test_refuses_managed_session_with_different_workdir(
        self, _session_exists, _require_cmd
    ):
        values = {
            SESSION_MANAGED_OPTION: "1",
            SESSION_WORKDIR_OPTION: "/old/project",
            SESSION_COMMAND_OPTION: "codex",
        }
        with patch(
            "codex_tmux_status_watch.tmux_get_option",
            side_effect=lambda _session, option: values[option],
        ):
            with self.assertRaisesRegex(RuntimeError, "参数不匹配"):
                start_codex_session("quota", "/tmp", "codex")

    @patch("codex_tmux_status_watch.require_cmd")
    @patch("codex_tmux_status_watch.tmux_session_exists", return_value=True)
    def test_reuses_matching_managed_session(self, _session_exists, _require_cmd):
        values = {
            SESSION_MANAGED_OPTION: "1",
            SESSION_WORKDIR_OPTION: "/tmp",
            SESSION_COMMAND_OPTION: "codex",
        }
        with patch(
            "codex_tmux_status_watch.tmux_get_option",
            side_effect=lambda _session, option: values[option],
        ):
            self.assertFalse(start_codex_session("quota", "/tmp", "codex"))


if __name__ == "__main__":
    unittest.main()
