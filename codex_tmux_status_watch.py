#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime


DEFAULT_SESSION = "codex_quota_watch"

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def run(cmd, check=True):
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


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


def start_codex_session(session: str, workdir: str, codex_cmd: str) -> bool:
    """
    返回 True 表示新建了 tmux session。
    返回 False 表示复用了已有 tmux session。
    """
    if tmux_session_exists(session):
        return False

    if not os.path.isdir(workdir):
        raise RuntimeError(f"目录不存在：{workdir}")

    require_cmd("tmux")
    require_cmd(codex_cmd)

    run([
        "tmux",
        "new-session",
        "-d",
        "-s",
        session,
        "-c",
        workdir,
        codex_cmd,
    ])

    time.sleep(3)
    return True


def tmux_send_key(session: str, key: str):
    run(["tmux", "send-keys", "-t", session, key], check=False)


def tmux_send_text_slow(session: str, text: str, char_delay: float = 0.03):
    for ch in text:
        run(["tmux", "send-keys", "-t", session, ch], check=False)
        time.sleep(char_delay)


def clear_tmux_pane(session: str):
    """
    清空 Codex TUI 的当前屏幕和 tmux 历史，避免抓到旧的 /status 输出。
    """
    tmux_send_key(session, "C-l")
    time.sleep(0.1)
    run(["tmux", "clear-history", "-t", session], check=False)
    time.sleep(0.1)


def send_status(session: str, double_enter: bool = True):
    """
    向 Codex 输入 /status。
    你的环境里 /status 后需要额外回车，所以默认 double_enter=True。
    """
    tmux_send_key(session, "C-u")
    time.sleep(0.1)

    tmux_send_text_slow(session, "/status")
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
        "-S",
        f"-{lines}",
    ], check=False)

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

        if "codex-spark" in low or ("gpt-5" in low and "spark" in low):
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
                result["limit_5h_left_percent"] = int(m.group(1))

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
                result[target_left] = int(m.group(1))

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
        f"7days  : {weekly_text}",
        f"5.3Spark : {spark_weekly_text}",
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
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    os.replace(tmp_path, path)


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

    try:
        created = start_codex_session(args.session, workdir, args.cmd)
    except Exception as e:
        print(f"启动失败：{e}", file=sys.stderr)
        return 1

    if args.attach:
        os.execvp("tmux", ["tmux", "attach", "-t", args.session])

    if created:
        first_screen = capture_pane(args.session, args.lines)
        if looks_like_trust_prompt(first_screen):
            if args.auto_trust:
                accept_trust_prompt(args.session)
            else:
                print("检测到 Codex trust 目录提示。")
                print()
                print("请先手动进入 tmux：")
                print(f"  tmux attach -t {args.session}")
                print()
                print("选择 1 回车后，按 Ctrl+B 再按 D 断开。")
                print("或者下次运行时加：--auto-trust")
                return 2

    while True:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
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

            payload = {
                "timestamp": ts,
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
                print(format_compact(status, ts, workdir))

        except KeyboardInterrupt:
            raise

        except Exception as e:
            if not args.no_clear:
                clear_screen()
            print(f"[{ts}] 查询失败：{e}")
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
