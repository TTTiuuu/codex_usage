#!/usr/bin/env python3
import json
import os
import sys


def status_json_has_quota_values(path) -> bool:
    if not path or not os.path.exists(path):
        return False

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False

    if data.get("error"):
        return False

    status = data.get("status") or {}
    return any(
        status.get(key) is not None
        for key in ("weekly_left_percent", "spark_weekly_left_percent")
    )


def main(argv):
    if len(argv) != 2:
        print("Usage: codex_status_ready.py /path/to/codex_status.json", file=sys.stderr)
        return 2

    return 0 if status_json_has_quota_values(argv[1]) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
