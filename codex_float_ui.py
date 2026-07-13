#!/usr/bin/env python3
import json
import os
import re
import tkinter as tk
from datetime import datetime, timedelta


JSON_PATH = "/tmp/codex_status.json"
REFRESH_MS = 5000

BAR_WIDTH = 310
BAR_HEIGHT = 8
TIME_BAR_HEIGHT = 3
SNAP_DISTANCE = 24
H5_WINDOW_MINUTES = 5 * 60
WEEKLY_WINDOW_MINUTES = 7 * 24 * 60
TIME_WINDOWS = {
    "h5": H5_WINDOW_MINUTES,
    "weekly": WEEKLY_WINDOW_MINUTES,
}


def parse_reset_datetime(reset_text: str, now: datetime | None = None):
    if now is None:
        now = datetime.now()

    if not reset_text:
        return None

    text = reset_text.strip()
    if not text or text.upper() == "N/A":
        return None

    low = text.lower()
    if low.startswith("in "):
        total_minutes = 0
        matches = re.findall(
            r"(\d+)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes)",
            low,
        )
        for amount, unit in matches:
            amount = int(amount)
            if unit.startswith("d"):
                total_minutes += amount * 24 * 60
            elif unit.startswith("h"):
                total_minutes += amount * 60
            else:
                total_minutes += amount
        if total_minutes > 0:
            return now + timedelta(minutes=total_minutes)

    normalized = re.sub(r"\bat\b", "", text, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip().rstrip(".")

    year_formats = (
        ("%Y-%m-%d %H:%M:%S", normalized),
        ("%Y-%m-%d %H:%M", normalized),
        ("%Y %b %d %H:%M", f"{now.year} {normalized}"),
        ("%Y %b %d, %H:%M", f"{now.year} {normalized}"),
        ("%Y %b %d %I:%M %p", f"{now.year} {normalized}"),
        ("%Y %b %d, %I:%M %p", f"{now.year} {normalized}"),
        ("%Y %H:%M on %d %b", f"{now.year} {normalized}"),
        ("%Y %I:%M %p on %d %b", f"{now.year} {normalized}"),
    )
    for fmt, value in year_formats:
        try:
            parsed = datetime.strptime(value, fmt)
            if not normalized.startswith(str(now.year)) and parsed <= now:
                parsed = parsed.replace(year=now.year + 1)
            return parsed
        except ValueError:
            pass

    time_formats = ("%I:%M %p", "%H:%M")
    for fmt in time_formats:
        try:
            parsed_time = datetime.strptime(normalized, fmt).time()
            parsed = datetime.combine(now.date(), parsed_time)
            if parsed <= now:
                parsed += timedelta(days=1)
            return parsed
        except ValueError:
            pass

    return None


def time_remaining_percent(
    reset_text: str,
    window_minutes: int,
    now: datetime | None = None,
):
    if now is None:
        now = datetime.now()

    reset_dt = parse_reset_datetime(reset_text, now)
    if reset_dt is None or window_minutes <= 0:
        return None

    remaining_minutes = (reset_dt - now).total_seconds() / 60
    if remaining_minutes < 0:
        return None

    remaining_ratio = remaining_minutes / window_minutes
    remaining_percent = round(max(0, min(1, remaining_ratio)) * 100)
    return remaining_percent


def format_reset_text(
    prefix: str,
    reset_text: str,
    now: datetime | None = None,
) -> str:
    if not reset_text or reset_text == "N/A":
        return "N/A"

    if prefix != "weekly":
        return reset_text

    if now is None:
        now = datetime.now()

    reset_dt = parse_reset_datetime(reset_text, now)
    if reset_dt is None:
        return reset_text

    if reset_dt.date() == now.date():
        return reset_dt.strftime("%H:%M")

    return f"{reset_dt.month}.{reset_dt.day}"


def status_is_stale(timestamp: str, now: datetime | None = None) -> bool:
    if now is None:
        now = datetime.now()

    try:
        updated_at = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return True

    return (now - updated_at) > timedelta(minutes=3)


def quota_row_is_available(left_percent) -> bool:
    return left_percent is not None


def snap_position(
    x: int,
    y: int,
    window_width: int,
    window_height: int,
    screen_width: int,
    screen_height: int,
    snap_distance: int = SNAP_DISTANCE,
    ignored_edges: set[str] | None = None,
):
    if ignored_edges is None:
        ignored_edges = set()

    max_x = max(0, screen_width - window_width)
    max_y = max(0, screen_height - window_height)

    if "left" not in ignored_edges and abs(x) <= snap_distance:
        x = 0
    elif "right" not in ignored_edges and abs(max_x - x) <= snap_distance:
        x = max_x

    if "top" not in ignored_edges and abs(y) <= snap_distance:
        y = 0
    elif "bottom" not in ignored_edges and abs(max_y - y) <= snap_distance:
        y = max_y

    return x, y


class CodexFloatingUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Codex Usage")

        # 悬浮、半透明、无边框
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.94)
        self.root.overrideredirect(True)

        self.drag_x = 0
        self.drag_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0

        self.build_ui()
        self.position_window()
        self.bind_drag_events()
        self.update_ui()

    def position_window(self):
        self.root.update_idletasks()

        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = self.root.winfo_reqwidth()
        window_height = self.root.winfo_reqheight()

        margin = 24
        x = max(margin, screen_width - window_width - margin)
        y = min(80, max(margin, screen_height - window_height - margin))

        self.root.geometry(f"+{x}+{y}")

    def build_ui(self):
        self.frame = tk.Frame(
            self.root,
            bg="#111111",
            padx=11,
            pady=5,
            highlightthickness=1,
            highlightbackground="#2c2c2c",
        )
        self.frame.pack()

        self.build_section("5h", "h5")
        self.build_section("7d", "weekly")

    def build_section(self, name, attr_prefix):
        container = tk.Frame(self.frame, bg="#111111")
        container.pack(fill="x", pady=(0, 2))

        label = tk.Label(
            container,
            text=name,
            bg="#111111",
            fg="#b0b0b0",
            font=("Ubuntu Mono", 10, "bold"),
            width=2,
            anchor="w",
        )
        label.pack(side="left", padx=(0, 4))

        bar_group = tk.Frame(container, bg="#111111")
        bar_group.pack(side="left", padx=(0, 4), pady=(1, 0))

        bar_canvas = tk.Canvas(
            bar_group,
            width=BAR_WIDTH,
            height=BAR_HEIGHT,
            bg="#111111",
            highlightthickness=0,
            bd=0,
        )
        bar_canvas.pack(fill="x")

        time_bar_canvas = tk.Canvas(
            bar_group,
            width=BAR_WIDTH,
            height=TIME_BAR_HEIGHT,
            bg="#111111",
            highlightthickness=0,
            bd=0,
        )
        time_bar_canvas.pack(fill="x", pady=(0, 0))

        value = tk.Label(
            container,
            text="N/A",
            bg="#111111",
            fg="#ffffff",
            font=("Ubuntu Mono", 10, "bold"),
            width=4,
            anchor="e",
        )
        value.pack(side="left")

        reset = tk.Label(
            container,
            text="N/A",
            bg="#111111",
            fg="#8a8a8a",
            font=("Ubuntu Mono", 8),
            anchor="w",
        )
        reset.pack(side="left", padx=(4, 0))

        setattr(self, f"{attr_prefix}_container", container)
        setattr(self, f"{attr_prefix}_label", label)
        setattr(self, f"{attr_prefix}_value", value)
        setattr(self, f"{attr_prefix}_bar", bar_canvas)
        setattr(self, f"{attr_prefix}_time_bar", time_bar_canvas)
        setattr(self, f"{attr_prefix}_reset", reset)

    def set_section_visible(self, prefix, visible):
        container = getattr(self, f"{prefix}_container")
        is_mapped = bool(container.winfo_ismapped())

        if visible and not is_mapped:
            before = getattr(self, "weekly_container", None) if prefix == "h5" else None
            container.pack(fill="x", pady=(0, 2), before=before)
        elif not visible and is_mapped:
            container.pack_forget()

    def bind_drag_events(self):
        self.bind_drag_recursive(self.frame)

    def bind_drag_recursive(self, widget):
        widget.bind("<ButtonPress-1>", self.start_drag)
        widget.bind("<B1-Motion>", self.drag)
        widget.bind("<ButtonRelease-1>", self.end_drag)

        for child in widget.winfo_children():
            self.bind_drag_recursive(child)

    def start_drag(self, event):
        self.drag_x = self.root.winfo_pointerx() - self.root.winfo_x()
        self.drag_y = self.root.winfo_pointery() - self.root.winfo_y()
        self.drag_start_x = self.root.winfo_x()
        self.drag_start_y = self.root.winfo_y()

    def drag(self, event):
        x = self.root.winfo_pointerx() - self.drag_x
        y = self.root.winfo_pointery() - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def end_drag(self, event):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        max_x = max(0, self.root.winfo_screenwidth() - self.root.winfo_width())
        max_y = max(0, self.root.winfo_screenheight() - self.root.winfo_height())
        ignored_edges = set()

        if abs(self.drag_start_x) <= SNAP_DISTANCE and x > self.drag_start_x:
            ignored_edges.add("left")
        if abs(max_x - self.drag_start_x) <= SNAP_DISTANCE and x < self.drag_start_x:
            ignored_edges.add("right")
        if abs(self.drag_start_y) <= SNAP_DISTANCE and y > self.drag_start_y:
            ignored_edges.add("top")
        if abs(max_y - self.drag_start_y) <= SNAP_DISTANCE and y < self.drag_start_y:
            ignored_edges.add("bottom")

        x, y = snap_position(
            x,
            y,
            self.root.winfo_width(),
            self.root.winfo_height(),
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
            ignored_edges=ignored_edges,
        )
        self.root.geometry(f"+{x}+{y}")

    def read_status(self):
        if not os.path.exists(JSON_PATH):
            return None, f"JSON not found:\n{JSON_PATH}"

        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            status = data.get("status") or {}
            timestamp = data.get("timestamp") or ""

            return {
                "timestamp": timestamp,
                "h5_left": status.get("limit_5h_left_percent"),
                "h5_reset": status.get("limit_5h_reset") or "N/A",
                "weekly_left": status.get("weekly_left_percent"),
                "weekly_reset": status.get("weekly_reset") or "N/A",
            }, None

        except Exception as e:
            return None, f"Read error:\n{e}"

    def color_by_left(self, left_percent):
        if left_percent is None:
            return "#5a5a5a"

        try:
            left_percent = int(left_percent)
        except Exception:
            return "#5a5a5a"

        if left_percent <= 10:
            return "#ff6b6b"   # red
        if left_percent <= 30:
            return "#f0b35a"   # orange
        return "#5aa9ff"       # blue

    def draw_progress_bar(self, canvas, left_percent, stale=False):
        canvas.delete("all")

        # 使用实际 canvas 宽度，保证右侧和百分比右侧对齐
        width = max(canvas.winfo_width(), BAR_WIDTH)
        height = BAR_HEIGHT
        pad = 1

        # 背景
        canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill="#3a1f1f" if stale else "#262626",
            outline="#3a1f1f" if stale else "#262626",
        )

        if left_percent is None:
            return

        try:
            left_percent = int(left_percent)
        except Exception:
            return

        left_percent = max(0, min(100, left_percent))
        fill_width = int((left_percent / 100) * width)
        fill_color = "#ff6b6b" if stale else self.color_by_left(left_percent)

        if fill_width > 0:
            canvas.create_rectangle(
                pad,
                pad,
                fill_width,
                height - pad,
                fill=fill_color,
                outline=fill_color,
            )

    def draw_time_bar(self, canvas, remaining_percent, stale=False):
        canvas.delete("all")

        width = max(canvas.winfo_width(), BAR_WIDTH)
        height = TIME_BAR_HEIGHT
        pad = 1

        canvas.create_rectangle(
            0,
            0,
            width,
            height,
            fill="#3a1f1f" if stale else "#1f1f1f",
            outline="#3a1f1f" if stale else "#1f1f1f",
        )

        if remaining_percent is None:
            return

        try:
            remaining_percent = int(remaining_percent)
        except Exception:
            return

        remaining_percent = max(0, min(100, remaining_percent))
        fill_width = int((remaining_percent / 100) * width)

        if fill_width > 0:
            canvas.create_rectangle(
                pad,
                0,
                fill_width,
                height,
                fill="#ff6b6b" if stale else "#7a7a7a",
                outline="#ff6b6b" if stale else "#7a7a7a",
            )

    def format_time(self, timestamp: str) -> str:
        if not timestamp:
            return "updated: N/A"

        try:
            dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            return f"updated: {dt.strftime('%H:%M:%S')}"
        except Exception:
            return f"updated: {timestamp}"

    def update_section(self, prefix, left_value, reset_text, stale=False):
        value_label = getattr(self, f"{prefix}_value")
        bar_canvas = getattr(self, f"{prefix}_bar")
        time_bar_canvas = getattr(self, f"{prefix}_time_bar")
        reset_label = getattr(self, f"{prefix}_reset")

        if left_value is None:
            value_label.config(text="N/A", fg="#ff6b6b" if stale else "#ffcc66")
            reset_label.config(text="N/A")
            self.draw_progress_bar(bar_canvas, None, stale=stale)
            self.draw_time_bar(time_bar_canvas, None, stale=stale)
            return

        try:
            left_value = int(left_value)
        except Exception:
            value_label.config(text="N/A", fg="#ff6b6b" if stale else "#ffcc66")
            reset_label.config(text="N/A")
            self.draw_progress_bar(bar_canvas, None, stale=stale)
            self.draw_time_bar(time_bar_canvas, None, stale=stale)
            return

        value_label.config(
            text=f"{left_value}%",
            fg="#ff6b6b" if stale else self.color_by_left(left_value),
        )

        reset_label.config(text=format_reset_text(prefix, reset_text))

        # 等布局完成后再绘制，确保 canvas 宽度正确
        self.root.after(
            10,
            lambda: self.draw_progress_bar(bar_canvas, left_value, stale=stale),
        )
        time_percent = time_remaining_percent(reset_text, TIME_WINDOWS.get(prefix, 0))
        self.root.after(
            10,
            lambda: self.draw_time_bar(time_bar_canvas, time_percent, stale=stale),
        )

    def update_ui(self):
        data, error = self.read_status()

        if error:
            self.set_section_visible("h5", True)
            self.set_section_visible("weekly", True)
            self.update_section("h5", None, "N/A", stale=True)
            self.update_section("weekly", None, "N/A", stale=True)
        else:
            stale = status_is_stale(data["timestamp"])
            show_h5 = quota_row_is_available(data["h5_left"])
            self.set_section_visible("h5", show_h5)
            if show_h5:
                self.update_section("h5", data["h5_left"], data["h5_reset"], stale=stale)
            self.update_section(
                "weekly",
                data["weekly_left"],
                data["weekly_reset"],
                stale=stale,
            )

        self.root.after(REFRESH_MS, self.update_ui)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    CodexFloatingUI().run()
