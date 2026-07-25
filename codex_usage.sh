#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
WATCH_SCRIPT="$SCRIPT_DIR/codex_tmux_status_watch.py"
UI_SCRIPT="$SCRIPT_DIR/codex_float_ui.py"
READY_SCRIPT="$SCRIPT_DIR/codex_status_ready.py"
TMUX_SESSION="${CODEX_USAGE_TMUX_SESSION:-codex_quota_watch}"

if [ -n "${XDG_RUNTIME_DIR:-}" ]; then
  RUNTIME_DIR="$XDG_RUNTIME_DIR/codex-usage"
else
  RUNTIME_DIR="${TMPDIR:-/tmp}/codex-usage-$(id -u)"
fi

STATE_ROOT="${XDG_STATE_HOME:-${HOME:?HOME is not set}/.local/state}"
STATE_DIR="$STATE_ROOT/codex-usage"
STATUS_PATH="$RUNTIME_DIR/status.json"
WATCH_PID="$RUNTIME_DIR/watcher.pid"
UI_PID="$RUNTIME_DIR/ui.pid"
LOCK_PATH="$RUNTIME_DIR/manager.lock"
WATCH_LOG="$STATE_DIR/watcher.log"
UI_LOG="$STATE_DIR/ui.log"
UI_STATE_PATH="$STATE_DIR/ui-state.json"

export CODEX_USAGE_STATUS_PATH="$STATUS_PATH"
export CODEX_USAGE_UI_STATE_PATH="$UI_STATE_PATH"

usage() {
  cat <<EOF
Usage:
  ./codex_usage.sh start [WORKDIR] [--auto-trust]
  ./codex_usage.sh stop
  ./codex_usage.sh restart [WORKDIR] [--auto-trust]
  ./codex_usage.sh status
  ./codex_usage.sh logs

Running without a command is the same as "start".
EOF
}

ensure_secure_dir() {
  local path="$1"

  if [ -L "$path" ]; then
    echo "ERROR: refusing symlinked runtime directory: $path" >&2
    return 1
  fi

  mkdir -p "$path"
  if [ "$(stat -c '%u' "$path")" != "$(id -u)" ]; then
    echo "ERROR: directory is not owned by the current user: $path" >&2
    return 1
  fi
  chmod 700 "$path"
}

ensure_runtime() {
  ensure_secure_dir "$RUNTIME_DIR"
  ensure_secure_dir "$STATE_DIR"
}

read_pid() {
  local file="$1"
  local pid=""

  [ -f "$file" ] || return 1
  IFS= read -r pid < "$file" || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$pid"
}

process_matches() {
  local pid="$1"
  local script="$2"
  local cmdline=""

  kill -0 "$pid" 2>/dev/null || return 1
  cmdline="$(tr '\0' '\n' 2>/dev/null < "/proc/$pid/cmdline")" || return 1
  grep -Fqx -- "$script" <<< "$cmdline"
}

stop_pid_file() {
  local label="$1"
  local file="$2"
  local script="$3"
  local pid=""

  pid="$(read_pid "$file" 2>/dev/null || true)"
  if [ -z "$pid" ]; then
    rm -f "$file"
    return 0
  fi

  if ! process_matches "$pid" "$script"; then
    echo "Ignoring stale $label PID file: $pid"
    rm -f "$file"
    return 0
  fi

  echo "Stopping $label (PID $pid)..."
  kill "$pid" 2>/dev/null || true

  for _ in $(seq 1 40); do
    process_matches "$pid" "$script" || break
    sleep 0.1
  done

  if process_matches "$pid" "$script"; then
    echo "$label did not stop in time; sending SIGKILL."
    kill -KILL "$pid" 2>/dev/null || true
  fi

  rm -f "$file"
}

session_is_managed() {
  command -v tmux >/dev/null 2>&1 || return 1
  [ "$(tmux show-options -v -t "$TMUX_SESSION" @codex_usage_managed 2>/dev/null || true)" = "1" ]
}

stop_impl() {
  stop_pid_file "floating UI" "$UI_PID" "$UI_SCRIPT"
  stop_pid_file "watcher" "$WATCH_PID" "$WATCH_SCRIPT"

  if command -v tmux >/dev/null 2>&1 && tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    if session_is_managed; then
      echo "Stopping managed tmux session: $TMUX_SESSION"
      tmux kill-session -t "$TMUX_SESSION" || true
    else
      echo "Leaving unmanaged tmux session untouched: $TMUX_SESSION" >&2
    fi
  fi

  rm -f "$STATUS_PATH"
}

require_start_dependencies() {
  local cmd
  for cmd in python3 tmux flock; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "ERROR: required command not found: $cmd" >&2
      return 1
    fi
  done

  for file in "$WATCH_SCRIPT" "$UI_SCRIPT" "$READY_SCRIPT"; do
    if [ ! -f "$file" ]; then
      echo "ERROR: required file not found: $file" >&2
      return 1
    fi
  done
}

parse_start_args() {
  START_WORKDIR=""
  START_AUTO_TRUST=0

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --auto-trust)
        START_AUTO_TRUST=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      --*)
        echo "ERROR: unknown option: $1" >&2
        usage >&2
        exit 2
        ;;
      *)
        if [ -n "$START_WORKDIR" ]; then
          echo "ERROR: only one WORKDIR may be supplied" >&2
          exit 2
        fi
        START_WORKDIR="$1"
        ;;
    esac
    shift
  done

  START_WORKDIR="${START_WORKDIR:-$PWD}"
  if [ ! -d "$START_WORKDIR" ]; then
    echo "ERROR: workdir does not exist: $START_WORKDIR" >&2
    exit 1
  fi
  START_WORKDIR="$(cd "$START_WORKDIR" && pwd -P)"
}

start_impl() {
  local watcher_pid=""
  local ui_pid=""
  local ready=0
  local -a watcher_args

  parse_start_args "$@"
  require_start_dependencies

  watcher_pid="$(read_pid "$WATCH_PID" 2>/dev/null || true)"
  ui_pid="$(read_pid "$UI_PID" 2>/dev/null || true)"
  if [ -n "$watcher_pid" ] && [ -n "$ui_pid" ] \
    && process_matches "$watcher_pid" "$WATCH_SCRIPT" \
    && process_matches "$ui_pid" "$UI_SCRIPT"; then
    echo "Codex Usage is already running."
    status_impl
    return 0
  fi

  # Clean up only processes recorded by this instance. Never scan globally.
  stop_impl
  rm -f "$STATUS_PATH"
  : > "$WATCH_LOG"
  : > "$UI_LOG"

  watcher_args=(
    "$WATCH_SCRIPT"
    "$START_WORKDIR"
    --interval 60
    --json-out "$STATUS_PATH"
  )
  if [ "$START_AUTO_TRUST" -eq 1 ]; then
    watcher_args+=(--auto-trust)
  fi

  echo "Starting Codex Usage..."
  echo "Workdir: $START_WORKDIR"

  nohup python3 -u "${watcher_args[@]}" > "$WATCH_LOG" 2>&1 9>&- &
  watcher_pid=$!
  printf '%s\n' "$watcher_pid" > "$WATCH_PID"

  # Show the UI immediately. It can display the temporary unavailable state
  # while Codex refreshes the quota data in the background.
  nohup python3 -u "$UI_SCRIPT" > "$UI_LOG" 2>&1 9>&- &
  ui_pid=$!
  printf '%s\n' "$ui_pid" > "$UI_PID"
  sleep 1

  if ! process_matches "$ui_pid" "$UI_SCRIPT"; then
    echo "ERROR: floating UI failed to start." >&2
    tail -n 40 "$UI_LOG" >&2 || true
    stop_impl
    return 1
  fi

  # The watcher retries every 60 seconds. Allow enough time for a second
  # /status query when Codex initially replies that limits are refreshing.
  for _ in $(seq 1 90); do
    if python3 "$READY_SCRIPT" "$STATUS_PATH"; then
      ready=1
      break
    fi

    if ! process_matches "$watcher_pid" "$WATCH_SCRIPT"; then
      echo "ERROR: watcher exited during startup." >&2
      tail -n 40 "$WATCH_LOG" >&2 || true
      stop_impl
      return 1
    fi
    sleep 1
  done

  if [ "$ready" -ne 1 ]; then
    echo "WARNING: quota data is still refreshing after 90 seconds." >&2
    tail -n 40 "$WATCH_LOG" >&2 || true
  fi

  echo "Started successfully."
  echo "Watcher PID: $watcher_pid"
  echo "UI PID     : $ui_pid"
  echo "Status     : $SCRIPT_DIR/codex_usage.sh status"
  echo "Stop       : $SCRIPT_DIR/codex_usage.sh stop"
}

status_impl() {
  local watcher_pid=""
  local ui_pid=""
  local watcher_state="stopped"
  local ui_state="stopped"

  watcher_pid="$(read_pid "$WATCH_PID" 2>/dev/null || true)"
  ui_pid="$(read_pid "$UI_PID" 2>/dev/null || true)"

  if [ -n "$watcher_pid" ] && process_matches "$watcher_pid" "$WATCH_SCRIPT"; then
    watcher_state="running (PID $watcher_pid)"
  fi
  if [ -n "$ui_pid" ] && process_matches "$ui_pid" "$UI_SCRIPT"; then
    ui_state="running (PID $ui_pid)"
  fi

  echo "Watcher : $watcher_state"
  echo "UI      : $ui_state"
  if python3 "$READY_SCRIPT" "$STATUS_PATH" 2>/dev/null; then
    echo "Data    : ready"
  elif [ -f "$STATUS_PATH" ]; then
    echo "Data    : unavailable or unhealthy"
  else
    echo "Data    : not found"
  fi
  echo "Runtime : $RUNTIME_DIR"
  echo "Logs    : $STATE_DIR"
}

logs_impl() {
  echo "== watcher =="
  tail -n 80 "$WATCH_LOG" 2>/dev/null || echo "No watcher log."
  echo
  echo "== floating UI =="
  tail -n 80 "$UI_LOG" 2>/dev/null || echo "No UI log."
}

ACTION="${1:-start}"
case "$ACTION" in
  start|stop|restart|status|logs|-h|--help)
    [ "$#" -gt 0 ] && shift
    ;;
  *)
    ACTION="start"
    ;;
esac

case "$ACTION" in
  -h|--help)
    usage
    ;;
  status)
    status_impl
    ;;
  logs)
    logs_impl
    ;;
  start|stop|restart)
    ensure_runtime
    exec 9> "$LOCK_PATH"
    flock -x 9
    case "$ACTION" in
      start)
        start_impl "$@"
        ;;
      stop)
        stop_impl
        echo "Codex Usage stopped."
        ;;
      restart)
        stop_impl
        start_impl "$@"
        ;;
    esac
    ;;
esac
