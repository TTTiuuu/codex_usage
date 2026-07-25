#!/usr/bin/env python3
import argparse
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import time
from datetime import datetime


DEFAULT_SESSION = "codex_quota_watch"
SESSION_MANAGED_OPTION = "@codex_usage_managed"
SESSION_WORKDIR_OPTION = "@codex_usage_workdir"
SESSION_COMMAND_OPTION = "@codex_usage_command"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
APP_SERVER_TIMEOUT_SECONDS = 20


def run(cmd, check=True):
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no error output"
        raise RuntimeError(f"{cmd[0]} failed ({result.returncode}): {detail}")
    return result


def require_cmd(cmd: str):
    if not shutil.which(cmd):
        raise RuntimeError(f"找不到命令：{cmd}")


def strip_ansi(text: str) -> str:
    text = ANSI_RE.sub("", text)
    text = text.replace("\r", "\n")
    return text


def clear_screen():
    print("\033[2J\033[H", end="")


def tmux_session_exists(session: str) -> bool:
    r = subprocess.run(
        ["tmux", "has-session", "-t", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def tmux_get_option(session: str, option: str) -> str:
    result = run(
        ["tmux", "show-options", "-v", "-t", session, option],
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def tmux_set_option(session: str, option: str, value: str):
    run(["tmux", "set-option", "-t", session, option, value])


def start_codex_session(session: str, workdir: str, codex_cmd: str) -> bool:
    """
    返回 True 表示新建了 tmux session。
    返回 False 表示复用了已有 tmux session。
    """
    if not os.path.isdir(workdir):
        raise RuntimeError(f"目录不存在：{workdir}")

    require_cmd("tmux")
    require_cmd(codex_cmd)

    if tmux_session_exists(session):
        managed = tmux_get_option(session, SESSION_MANAGED_OPTION)
        existing_workdir = tmux_get_option(session, SESSION_WORKDIR_OPTION)
        existing_command = tmux_get_option(session, SESSION_COMMAND_OPTION)

        if managed != "1":
            raise RuntimeError(
                f"tmux 会话 {session!r} 已存在，但不是本工具创建的；"
                "为避免干扰现有会话，拒绝复用"
            )
        if existing_workdir != workdir or existing_command != codex_cmd:
            raise RuntimeError(
                f"tmux 会话 {session!r} 的参数不匹配："
                f"workdir={existing_workdir!r}, command={existing_command!r}"
            )
        return False

    run([
        "tmux",
        "new-session",
        "-d",
        "-x",
        "200",
        "-y",
        "50",
        "-s",
        session,
        "-c",
        workdir,
        codex_cmd,
    ])

    tmux_set_option(session, SESSION_MANAGED_OPTION, "1")
    tmux_set_option(session, SESSION_WORKDIR_OPTION, workdir)
    tmux_set_option(session, SESSION_COMMAND_OPTION, codex_cmd)

    time.sleep(3)
    return True


def tmux_send_key(session: str, key: str):
    run(["tmux", "send-keys", "-t", session, key])


def tmux_send_text(session: str, text: str):
    run(["tmux", "send-keys", "-t", session, "-l", text])


def clear_tmux_pane(session: str):
    """
    清空 Codex TUI 的当前屏幕和 tmux 历史，避免抓到旧的 /status 输出。
    """
    tmux_send_key(session, "C-l")
    time.sleep(0.1)
    run(["tmux", "clear-history", "-t", session])
    time.sleep(0.1)


def send_status(session: str, double_enter: bool = True):
    """
    向 Codex 输入 /status。
    你的环境里 /status 后需要额外回车，所以默认 double_enter=True。
    """
    tmux_send_key(session, "C-u")
    time.sleep(0.1)

    tmux_send_text(session, "/status")
    time.sleep(0.1)

    tmux_send_key(session, "Enter")

    if double_enter:
        time.sleep(0.25)
        tmux_send_key(session, "Enter")


def capture_pane(session: str, lines: int = 120) -> str:
    r = run([
        "tmux",
        "capture-pane",
        "-t",
        session,
        "-p",
        "-J",
        "-S",
        f"-{lines}",
    ])

    return strip_ansi(r.stdout)


def looks_like_trust_prompt(text: str) -> bool:
    low = text.lower()
    return (
        "do you trust the contents of this directory" in low
        or "yes, continue" in low
        or "no, quit" in low
    )


def accept_trust_prompt(session: str):
    tmux_send_key(session, "1")
    time.sleep(0.1)
    tmux_send_key(session, "Enter")
    time.sleep(1)


def clean_line(line: str) -> str:
    """
    去掉 Codex box drawing 边框字符。
    """
    line = line.strip()
    line = line.strip("│")
    line = line.strip()
    return line


def status_needs_limit_refresh(text: str) -> bool:
    clean = strip_ansi(text).lower()
    return "limits:" in clean and "refresh requested" in clean


def _weekly_window(snapshot: dict) -> dict:
    windows = [
        window
        for key in ("primary", "secondary")
        if isinstance((window := snapshot.get(key)), dict)
    ]
    if not windows:
        return {}

    # Pro accounts may expose a short primary window and a weekly secondary
    # window. Other plans currently expose the weekly window as primary.
    return max(
        windows,
        key=lambda window: window.get("windowDurationMins") or 0,
    )


def _reset_text(resets_at) -> str:
    if not isinstance(resets_at, (int, float)):
        return ""
    return datetime.fromtimestamp(resets_at).strftime("%H:%M on %d %b")


def parse_app_server_rate_limits(payload: dict) -> dict:
    """
    Convert account/rateLimits/read into the status shape consumed by the UI.
    """
    result = parse_status("")
    by_limit_id = payload.get("rateLimitsByLimitId")
    if not isinstance(by_limit_id, dict):
        by_limit_id = {}

    default_snapshot = payload.get("rateLimits")
    if isinstance(default_snapshot, dict) and "codex" not in by_limit_id:
        by_limit_id = {"codex": default_snapshot, **by_limit_id}

    weekly_snapshot = None
    spark_snapshot = None
    for limit_id, snapshot in by_limit_id.items():
        if not isinstance(snapshot, dict):
            continue
        limit_name = str(snapshot.get("limitName") or "")
        identifier = f"{limit_id} {limit_name}".lower()
        if "spark" in identifier or "bengalfox" in identifier:
            spark_snapshot = snapshot
        elif limit_id == "codex" or weekly_snapshot is None:
            weekly_snapshot = snapshot

    def apply_snapshot(snapshot, left_key, reset_key):
        if not isinstance(snapshot, dict):
            return
        window = _weekly_window(snapshot)
        used_percent = window.get("usedPercent")
        if isinstance(used_percent, int) and 0 <= used_percent <= 100:
            result[left_key] = 100 - used_percent
        result[reset_key] = _reset_text(window.get("resetsAt"))

    apply_snapshot(
        weekly_snapshot,
        "weekly_left_percent",
        "weekly_reset",
    )
    apply_snapshot(
        spark_snapshot,
        "spark_weekly_left_percent",
        "spark_weekly_reset",
    )
    return result


def query_app_server_rate_limits(codex_cmd: str) -> dict:
    """
    Read quota data through Codex's local app-server protocol.

    This avoids depending on TUI rendering and remains compatible with older
    Codex versions because callers can fall back to /status screen parsing.
    """
    require_cmd(codex_cmd)
    requests = "\n".join([
        json.dumps({
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {
                    "name": "codex-usage",
                    "title": "Codex Usage",
                    "version": "1.0.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        }),
        json.dumps({
            "id": 2,
            "method": "account/rateLimits/read",
            "params": None,
        }),
        "",
    ])

    process = subprocess.Popen(
        [codex_cmd, "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    response = None
    stderr_text = ""
    deadline = time.monotonic() + APP_SERVER_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    try:
        process.stdin.write(requests)
        process.stdin.flush()

        while time.monotonic() < deadline:
            remaining = max(0, deadline - time.monotonic())
            events = selector.select(timeout=remaining)
            if not events:
                if process.poll() is not None:
                    break
                continue

            line = process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == 2:
                response = message
                break
    finally:
        selector.close()
        if process.stdin is not None:
            process.stdin.close()
            process.stdin = None
        if process.poll() is None:
            process.terminate()
        try:
            _, stderr_text = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr_text = process.communicate()

    if response is None and time.monotonic() >= deadline:
        raise RuntimeError("Codex 本地额度接口查询超时")

    if response is None:
        detail = stderr_text.strip() or "未收到 rateLimits 响应"
        raise RuntimeError(f"Codex 本地额度接口失败：{detail}")
    if response.get("error"):
        raise RuntimeError(f"Codex 本地额度接口失败：{response['error']}")

    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Codex 本地额度接口返回了无效数据")

    status = parse_app_server_rate_limits(result)
    if not status_has_displayable_quota(status):
        raise RuntimeError("Codex 本地额度接口未返回 Weekly 或 Spark 额度")
    return status


def parse_status(text: str) -> dict:
    """
    从 Codex /status 屏幕中提取：
    - model
    - account
    - 5h left percent
    - 5h reset time
    - weekly left percent
    - weekly reset time
    - spark weekly left percent
    - spark weekly reset time
    """
    result = {
        "model": "",
        "account": "",
        "limit_5h_left_percent": None,
        "limit_5h_reset": "",
        "weekly_left_percent": None,
        "weekly_reset": "",
        "spark_weekly_left_percent": None,
        "spark_weekly_reset": "",
    }

    clean = strip_ansi(text)
    raw_lines = clean.splitlines()
    lines = [clean_line(ln) for ln in raw_lines]
    lines = [ln for ln in lines if ln]

    in_spark_section = False

    for i, ln in enumerate(lines):
        low = ln.lower()

        if low.startswith("model:"):
            result["model"] = ln.split(":", 1)[1].strip()
            in_spark_section = False
            continue

        if low.startswith("account:"):
            result["account"] = ln.split(":", 1)[1].strip()
            in_spark_section = False
            continue

        line_is_spark = "codex-spark" in low or ("gpt-5" in low and "spark" in low)
        if line_is_spark:
            in_spark_section = True
            # 不 continue — 这行本身可能就包含了额度数据

        if low.startswith("5h limit:"):
            if in_spark_section:
                # Spark 5h limit — skip, we only need spark weekly
                continue
            if result["limit_5h_left_percent"] is not None:
                continue

            m = re.search(r"(\d+)%\s+left", ln, re.IGNORECASE)
            if m:
                percent = int(m.group(1))
                if 0 <= percent <= 100:
                    result["limit_5h_left_percent"] = percent

            m = re.search(r"resets\s+([^)│]+)", ln, re.IGNORECASE)
            if m:
                result["limit_5h_reset"] = m.group(1).strip()
            else:
                if i + 1 < len(lines):
                    next_ln = lines[i + 1]
                    m2 = re.search(r"resets\s+([^)│]+)", next_ln, re.IGNORECASE)
                    if m2:
                        result["limit_5h_reset"] = m2.group(1).strip()
            continue

        if "weekly limit:" in low:
            if in_spark_section:
                if result["spark_weekly_left_percent"] is not None:
                    continue
                target_left = "spark_weekly_left_percent"
                target_reset = "spark_weekly_reset"
            else:
                if result["weekly_left_percent"] is not None:
                    continue
                target_left = "weekly_left_percent"
                target_reset = "weekly_reset"

            m = re.search(r"(\d+)%\s+left", ln, re.IGNORECASE)
            if m:
                percent = int(m.group(1))
                if 0 <= percent <= 100:
                    result[target_left] = percent

            # reset 可能在同一行，也可能在下一行
            m = re.search(r"resets\s+([^)│]+)", ln, re.IGNORECASE)
            if m:
                result[target_reset] = m.group(1).strip()
            else:
                if i + 1 < len(lines):
                    next_ln = lines[i + 1]
                    m2 = re.search(r"resets\s+([^)│]+)", next_ln, re.IGNORECASE)
                    if m2:
                        result[target_reset] = m2.group(1).strip()
            if target_left == "spark_weekly_left_percent":
                # Spark 周额度是该区块的最后一项；之后的普通额度不能继续
                # 沿用 Spark 上下文。
                in_spark_section = False
            continue

    return result


def format_compact(status: dict, ts: str, workdir: str = "") -> str:
    model = status.get("model") or "N/A"
    account = status.get("account") or "N/A"

    weekly_left = status.get("weekly_left_percent")
    weekly_reset = status.get("weekly_reset") or "N/A"

    spark_weekly_left = status.get("spark_weekly_left_percent")
    spark_weekly_reset = status.get("spark_weekly_reset") or "N/A"

    weekly_text = (
        f"{weekly_left}% left, resets {weekly_reset}"
        if weekly_left is not None
        else "N/A"
    )
    spark_weekly_text = (
        f"{spark_weekly_left}% left, resets {spark_weekly_reset}"
        if spark_weekly_left is not None
        else "N/A"
    )

    lines = [
        "Codex Usage",
        f"Time   : {ts}",
        f"Model  : {model}",
        f"Account: {account}",
        f"Weekly: {weekly_text}",
        f"Spark : {spark_weekly_text}",
    ]

    if workdir:
        lines.append(f"Workdir: {workdir}")

    return "\n".join(lines)


def write_json(path: str, payload: dict):
    if not path:
        return

    path = os.path.abspath(os.path.expanduser(path))
    os.makedirs(os.path.dirname(path), exist_ok=True)

    tmp_path = path + ".tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, path)
    os.chmod(path, 0o600)


def status_has_displayable_quota(status: dict) -> bool:
    return any(
        status.get(key) is not None
        for key in ("weekly_left_percent", "spark_weekly_left_percent")
    )


def read_json(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_error_status(
    path: str,
    error: str,
    attempted_at: str,
    workdir: str,
    session: str,
):
    if not path:
        return

    previous = read_json(path)
    payload = {
        "timestamp": previous.get("timestamp", ""),
        "last_success_at": previous.get(
            "last_success_at", previous.get("timestamp", "")
        ),
        "attempted_at": attempted_at,
        "error": error,
        "workdir": workdir,
        "session": session,
        "status": previous.get("status") or parse_status(""),
    }
    write_json(path, payload)


def ensure_session_ready(args, workdir: str) -> bool:
    created = start_codex_session(args.session, workdir, args.cmd)
    if not created:
        return False

    first_screen = capture_pane(args.session, args.lines)
    if looks_like_trust_prompt(first_screen):
        if args.auto_trust:
            accept_trust_prompt(args.session)
        else:
            raise RuntimeError(
                "检测到 Codex 目录信任提示。请先手动信任该目录，"
                "或明确使用 --auto-trust"
            )
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Keep Codex running in tmux and show compact /status usage."
    )

    parser.add_argument(
        "workdir",
        help="进入 Codex 的目录，例如 /home/tanrui/temp/codexbar，当前目录可用 \"$PWD\"",
    )

    parser.add_argument(
        "--session",
        default=DEFAULT_SESSION,
        help=f"tmux session 名称，默认 {DEFAULT_SESSION}",
    )

    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="查询间隔秒数，默认 60",
    )

    parser.add_argument(
        "--cmd",
        default="codex",
        help="Codex 命令，默认 codex",
    )

    parser.add_argument(
        "--wait-after-status",
        type=float,
        default=4.0,
        help="发送 /status 后等待刷新秒数，默认 4.0",
    )

    parser.add_argument(
        "--lines",
        type=int,
        default=120,
        help="抓取 tmux 屏幕行数，默认 120",
    )

    parser.add_argument(
        "--single",
        action="store_true",
        help="只查询一次，不循环",
    )

    parser.add_argument(
        "--raw",
        action="store_true",
        help="调试用：显示完整 tmux 屏幕内容",
    )

    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="不清屏，适合日志调试",
    )

    parser.add_argument(
        "--no-double-enter",
        action="store_true",
        help="发送 /status 后不补第二次回车",
    )

    parser.add_argument(
        "--auto-trust",
        action="store_true",
        help="如果出现 trust 目录提示，自动输入 1 并回车",
    )

    parser.add_argument(
        "--json-out",
        default="",
        help="把结构化结果写入 JSON，例如 /tmp/codex_status.json",
    )

    parser.add_argument(
        "--attach",
        action="store_true",
        help="启动 tmux Codex 会话后直接 attach",
    )

    args = parser.parse_args()

    workdir = os.path.abspath(os.path.expanduser(args.workdir))
    double_enter = not args.no_double_enter

    if args.attach:
        try:
            ensure_session_ready(args, workdir)
        except Exception as e:
            print(f"启动失败：{e}", file=sys.stderr)
            return 1
        os.execvp("tmux", ["tmux", "attach", "-t", args.session])

    while True:
        attempted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            app_server_error = None
            try:
                status = query_app_server_rate_limits(args.cmd)
            except Exception as e:
                app_server_error = e
                ensure_session_ready(args, workdir)
                clear_tmux_pane(args.session)

                send_status(args.session, double_enter=double_enter)
                time.sleep(args.wait_after_status)
                screen_text = capture_pane(args.session, args.lines)

                if status_needs_limit_refresh(screen_text):
                    time.sleep(6)
                    send_status(args.session, double_enter=double_enter)
                    time.sleep(args.wait_after_status)
                    screen_text = capture_pane(args.session, args.lines)

                status = parse_status(screen_text)
            if not status_has_displayable_quota(status):
                detail = "未从 /status 输出中解析到 Weekly 或 Spark Weekly 额度"
                if app_server_error is not None:
                    detail = f"{app_server_error}；{detail}"
                raise RuntimeError(detail)

            succeeded_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            payload = {
                "timestamp": succeeded_at,
                "last_success_at": succeeded_at,
                "attempted_at": attempted_at,
                "error": "",
                "workdir": workdir,
                "session": args.session,
                "status": status,
            }

            write_json(args.json_out, payload)

            if not args.no_clear:
                clear_screen()

            if args.raw:
                print(screen_text.strip())
            else:
                print(format_compact(status, succeeded_at, workdir))

        except KeyboardInterrupt:
            raise

        except Exception as e:
            write_error_status(
                args.json_out,
                str(e),
                attempted_at,
                workdir,
                args.session,
            )
            if not args.no_clear:
                clear_screen()
            print(f"[{attempted_at}] 查询失败：{e}")
            print(f"可以查看真实 Codex 会话：tmux attach -t {args.session}")

        if args.single:
            break

        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
        raise SystemExit(0)
