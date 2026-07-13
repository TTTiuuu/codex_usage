#!/usr/bin/env bash
set -euo pipefail

JSON_PATH="/tmp/codex_status.json"
WATCH_LOG="/tmp/codex_status_watch.log"
UI_LOG="/tmp/codex_float_ui.log"
TMUX_SESSION="codex_quota_watch"

echo "Stopping Codex usage tools..."

# 强制杀掉所有旧 watcher 和 UI 进程（按进程名匹配，不依赖 PID 文件）
for OLD_PID in $(pgrep -f "codex_tmux_status_watch.py" 2>/dev/null || true); do
  echo "Killing old watcher pid: $OLD_PID"
  kill "$OLD_PID" 2>/dev/null || true
done
for OLD_PID in $(pgrep -f "codex_float_ui.py" 2>/dev/null || true); do
  echo "Killing old UI pid: $OLD_PID"
  kill "$OLD_PID" 2>/dev/null || true
done
sleep 1

# 关闭 tmux 中的 Codex 会话
if command -v tmux >/dev/null 2>&1; then
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "Killing tmux session: $TMUX_SESSION"
    tmux kill-session -t "$TMUX_SESSION" || true
  else
    echo "tmux session not found: $TMUX_SESSION"
  fi
fi

# 可选：清理 JSON
rm -f "$JSON_PATH"

echo
echo "Stopped."
echo "Logs kept:"
echo "  $WATCH_LOG"
echo "  $UI_LOG"
