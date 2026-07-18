#!/usr/bin/env bash
set -euo pipefail

umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
APPLICATIONS_DIR="${XDG_DATA_HOME:-${HOME:?HOME is not set}/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
MODE="${1:---menu}"

case "$MODE" in
  --menu)
    TARGET_DIRS=("$APPLICATIONS_DIR")
    ;;
  --autostart)
    TARGET_DIRS=("$AUTOSTART_DIR")
    ;;
  --all)
    TARGET_DIRS=("$APPLICATIONS_DIR" "$AUTOSTART_DIR")
    ;;
  -h|--help)
    echo "Usage: ./install_desktop_launcher.sh [--menu|--autostart|--all]"
    exit 0
    ;;
  *)
    echo "ERROR: unknown option: $MODE" >&2
    exit 2
    ;;
esac

for target_dir in "${TARGET_DIRS[@]}"; do
  mkdir -p "$target_dir"
  target="$target_dir/codex-usage-monitor.desktop"
  temp="$target.tmp"

  {
    echo "[Desktop Entry]"
    echo "Type=Application"
    echo "Name=Codex Usage Monitor"
    echo "Comment=Show Codex quota in a floating desktop window"
    printf 'Exec="%s/codex_usage.sh" start "%s"\n' "$SCRIPT_DIR" "$SCRIPT_DIR"
    echo "Icon=utilities-system-monitor"
    echo "Terminal=false"
    echo "Categories=Utility;System;"
    echo "StartupNotify=false"
  } > "$temp"

  chmod 600 "$temp"
  mv -f "$temp" "$target"
  echo "Installed: $target"
done
