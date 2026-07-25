#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-${HOME:?HOME is not set}/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/桌面}"
MODE="${1:---menu}"

case "$MODE" in
  --menu)
    TARGETS=("$APPLICATIONS_DIR/codex-usage-monitor.desktop")
    ;;
  --autostart)
    TARGETS=("$AUTOSTART_DIR/codex-usage-monitor.desktop")
    ;;
  --desktop)
    TARGETS=("$DESKTOP_DIR/Codex Usage Monitor.desktop")
    ;;
  --all)
    TARGETS=(
      "$APPLICATIONS_DIR/codex-usage-monitor.desktop"
      "$AUTOSTART_DIR/codex-usage-monitor.desktop"
      "$DESKTOP_DIR/Codex Usage Monitor.desktop"
    )
    ;;
  -h|--help)
    echo "Usage: ./install_desktop_launcher.sh [--menu|--autostart|--desktop|--all]"
    exit 0
    ;;
  *)
    echo "ERROR: unknown option: $MODE" >&2
    exit 2
    ;;
esac

for target in "${TARGETS[@]}"; do
  target_dir="$(dirname "$target")"
  mkdir -p "$target_dir"
  temp="$target.tmp"

  {
    echo "[Desktop Entry]"
    echo "Version=1.0"
    echo "Type=Application"
    echo "Name=Codex Usage Monitor"
    echo "Name[zh_CN]=Codex 额度监控"
    echo "Comment=Show Codex quota in a floating desktop window"
    printf 'Exec="%s/codex_usage.sh" start "%s"\n' "$SCRIPT_DIR" "$SCRIPT_DIR"
    printf 'Path=%s\n' "$SCRIPT_DIR"
    echo "Icon=utilities-system-monitor"
    echo "Terminal=false"
    echo "Categories=Utility;"
    echo "StartupNotify=false"
    echo "X-GNOME-Autostart-enabled=true"
  } > "$temp"

  if [ "$target_dir" = "$DESKTOP_DIR" ]; then
    chmod 755 "$temp"
  else
    chmod 600 "$temp"
  fi
  mv -f "$temp" "$target"

  if [ "$target_dir" = "$DESKTOP_DIR" ] && command -v gio >/dev/null 2>&1; then
    gio set "$target" metadata::trusted true 2>/dev/null || true
  fi
  echo "Installed: $target"
done
