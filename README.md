# Codex Usage Monitor

在 Linux 桌面上显示 Codex Weekly 和 Spark Weekly 额度，并用第二条进度条对比重置周期的剩余时间。

![运行效果](docs/images/image.png)

## 环境要求

- Python 3.10 或更高版本
- Codex CLI，且当前账号已经登录
- `tmux`、`flock` 和 Tkinter

Ubuntu/Debian 可以安装缺失的系统依赖：

```bash
sudo apt install -y tmux python3-tk util-linux
```

## 快速启动

```bash
./codex_usage.sh start
```

也可以指定承载 `/status` 会话的工作目录：

```bash
./codex_usage.sh start /path/to/project
```

默认不会自动确认 Codex 的目录信任提示。首次使用某个目录时，可以先在该目录运行一次 `codex` 并手动确认；如果确实希望自动确认，可显式执行：

```bash
./codex_usage.sh start /path/to/project --auto-trust
```

常用管理命令：

```bash
./codex_usage.sh status
./codex_usage.sh restart
./codex_usage.sh logs
./codex_usage.sh stop
```

旧的 `start_codex_usage.sh` 和 `stop_codex_usage.sh` 仍然可用，它们会转交给新的统一启动器。

## 添加到应用菜单或开机启动

添加到桌面应用菜单：

```bash
./install_desktop_launcher.sh --menu
```

启用图形会话登录后的自动启动：

```bash
./install_desktop_launcher.sh --autostart
```

两者都安装可使用 `--all`。桌面入口默认使用本项目目录启动，不会自动跳过目录信任。

## 界面说明

- 蓝色：额度剩余比例不低于周期剩余时间比例。
- 橙色：额度消耗速度快于时间流逝。
- 红色：后台刷新失败或最后一次成功数据超过 3 分钟。
- 左键拖动悬浮窗；右键可以关闭悬浮窗。
- 窗口位置会在下次启动时恢复。

## 运行与安全

- 状态和 PID 文件保存在 `$XDG_RUNTIME_DIR/codex-usage/`，权限为当前用户私有。
- 日志与窗口位置保存在 `$XDG_STATE_HOME/codex-usage/`，未设置时使用 `~/.local/state/codex-usage/`。
- 启停脚本只会操作 PID 文件中经过命令校验的进程，不会全局杀掉同名进程。
- watcher 会保留最后一次有效额度；刷新失败时记录错误并尝试恢复 tmux/Codex 会话。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

主要文件：

- `codex_usage.sh`：统一的 start/stop/restart/status/logs 管理入口
- `codex_tmux_status_watch.py`：管理隔离的 tmux 会话并读取 `/status`
- `codex_float_ui.py`：显示悬浮窗
- `install_desktop_launcher.sh`：安装应用菜单或自动启动入口
