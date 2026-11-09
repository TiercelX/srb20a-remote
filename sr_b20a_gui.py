"""Windows desktop controller for the existing SR-B20A SSH gateway."""
import asyncio
import concurrent.futures
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
import uuid
from types import SimpleNamespace
from tkinter import ttk, simpledialog, messagebox
from srb20a_config import get_address, save_address

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "sr-b20a.ps1"


def failure_message(result, fallback):
    error = result.get("error") or ((result.get("attempt_history") or [{}])[-1].get("error") or {})
    message = error.get("message") or fallback
    if result.get("uncertain_completion") or result.get("uncertain_after_write") or result.get("setter_attempted"):
        message += "；命令可能已发出，请先刷新状态再操作"
    return message


def gateway(command, value=None):
    args = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "mbp",
            "~/Tool/codex/sr-b20a/mbp-gateway.sh request"]
    request = {"version": 1, "device": "sr-b20a", "command": command,
               "request_id": str(uuid.uuid4())}
    if value is not None:
        request["value"] = value
    payload = json.dumps(request) + "\n"
    try:
        proc = subprocess.run(args, input=payload, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=360, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None, (proc.stderr or proc.stdout or "网关没有返回结果").strip()
        if proc.returncode or not result.get("ok"):
            return None, failure_message(result, "网关未确认操作")
        return result, None
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)


def direct(command, value=None):
    try:
        from soundbar_control import ADDRESS, run
        args = SimpleNamespace(command=command, value=value, address=ADDRESS,
                               scan_seconds=15, connect_timeout=20, attempts=1)
        result = asyncio.run(run(args))
        if not result.get("ok"):
            return None, failure_message(result, "蓝牙未确认操作")
        return result, None
    except Exception as exc:
        return None, str(exc)


ADVANCED_GUIDE = """下列高级设置需要先关闭音箱。除动态范围压缩外，操作会在开/关之间切换；设置完成后音箱自动开机。请根据指示灯确认实际结果。

HDMI 控制（CEC / ARC）
使用遥控器：关闭音箱后，长按 TV 至少 5 秒。TV 指示灯亮表示启用，灭表示禁用。ARC 需要启用 HDMI 控制。

自动待机
使用音箱本体：关闭后，按住输入键，同时按住电源键至少 5 秒。TV 指示灯亮表示禁用自动待机，灭表示启用。

儿童锁
使用遥控器：关闭音箱后，长按 INFO 至少 5 秒。TV 指示灯亮表示锁定，灭表示未锁定。

蓝牙待机
使用遥控器：关闭音箱后，长按 BLUETOOTH 至少 5 秒。蓝牙指示灯亮表示启用，灭表示禁用。关闭后可能无法通过蓝牙唤醒。

蓝牙功能
使用遥控器：关闭音箱后，长按 DIM 至少 5 秒。蓝牙指示灯亮表示启用，灭表示禁用。禁用后本程序和 MBP 网关将无法通过蓝牙连接，需要用遥控器重新启用。

杜比动态范围压缩
仅对 Dolby Digital 信号生效。关闭音箱后，长按遥控器对应按钮至少 5 秒：STANDARD = 最大压缩；MOVIE = 标准压缩；GAME = 不压缩。TV 指示灯红色 = 最大，TV 白色 = 标准，TV 和 OPTICAL 均为白色 = 不压缩。

播放信息
音箱开机时按遥控器 INFO，指示灯显示约 3 秒：TV 白色表示 Dolby Digital，TV 红色表示 DTS，OPTICAL 白色表示 AAC；TV 和 OPTICAL 均灭表示 PCM 或没有输入信号。

恢复出厂设置会清除设置，不在此提供快捷操作。完整步骤和指示灯说明请查阅官方使用指南。"""


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("SR-B20A 控制")
        self.root.geometry("520x690")
        self.root.minsize(480, 650)
        self.events = queue.Queue()
        self.state = None
        self.mode = tk.StringVar(value="本机蓝牙")
        self.busy = False
        self.controls = []
        self.extra_controls = []
        self.status_text = tk.StringVar(value="正在读取音箱状态…")
        self.detail_text = tk.StringVar(value="通过 MBP 蓝牙网关连接")
        self.volume = tk.IntVar(value=0)
        self.volume_text = tk.StringVar(value="-- / 50")
        self.state_text = tk.StringVar(value="等待状态")
        self.buttons = {}
        self.dimmer = tk.StringVar(value="off")
        self.sub_text = tk.StringVar(value="--")
        self.program_text = tk.StringVar(value="--")
        self.input = tk.StringVar(value="tv")
        self.build()
        root.after(100, self.poll)
        root.after(100, lambda: self.execute("status"))

    def build(self):
        style = ttk.Style()
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
        style.configure("Info.TLabel", font=("Microsoft YaHei UI", 10))
        outer = ttk.Frame(self.root, padding=20)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="SR-B20A", style="Title.TLabel").pack(side="left")
        refresh = ttk.Button(header, text="刷新状态", command=lambda: self.execute("status"))
        refresh.pack(side="right")
        ttk.Button(header, text="高级设置指南", command=self.show_advanced).pack(side="right", padx=8)
        self.refresh = refresh
        ttk.Label(outer, textvariable=self.state_text, style="Info.TLabel").pack(anchor="w", pady=(4, 6))
        mode_row = ttk.Frame(outer)
        mode_row.pack(fill="x", pady=(0, 10))
        ttk.Label(mode_row, text="连接方式").pack(side="left")
        self.mode_box = ttk.Combobox(mode_row, textvariable=self.mode, values=("本机蓝牙", "MBP 网关"), state="readonly", width=14)
        self.mode_box.pack(side="right")
        self.mode_box.bind("<<ComboboxSelected>>", self.mode_changed)
        power_row = ttk.Frame(outer)
        power_row.pack(fill="x", pady=(0, 8))
        ttk.Label(power_row, text="电源").pack(side="left")
        self.power_on = ttk.Button(power_row, text="开机", command=lambda: self.execute("power", "on"))
        self.power_on.pack(side="right")
        power_off = ttk.Button(power_row, text="待机", command=lambda: self.execute("power", "off"))
        power_off.pack(side="right", padx=6)
        self.controls.append(power_off)
        input_row = ttk.Frame(outer)
        input_row.pack(fill="x", pady=(0, 8))
        ttk.Label(input_row, text="输入").pack(side="left")
        for label, value in (("蓝牙", "bluetooth"), ("光纤", "optical"), ("电视", "tv")):
            button = ttk.Radiobutton(input_row, text=label, variable=self.input, value=value, command=lambda v=value: self.execute("input", v))
            button.pack(side="right", padx=3)
            self.controls.append(button)
        volume_header = ttk.Frame(outer)
        volume_header.pack(fill="x")
        ttk.Label(volume_header, text="音量", style="Info.TLabel").pack(side="left")
        ttk.Label(volume_header, textvariable=self.volume_text).pack(side="right")
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=(5, 18))
        scale = ttk.Scale(row, from_=0, to=50, variable=self.volume, command=self.volume_changed)
        scale.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.controls.append(scale)
        apply_button = ttk.Button(row, text="设置音量", command=lambda: self.execute("volume", self.volume.get()))
        apply_button.pack(side="right")
        self.controls.append(apply_button)
        sub_row = ttk.Frame(outer)
        sub_row.pack(fill="x", pady=(0, 8))
        ttk.Label(sub_row, text="低音炮音量").pack(side="left")
        for label, value in (("＋", "up"), ("－", "down")):
            button = ttk.Button(sub_row, text=label, width=4, command=lambda v=value: self.execute("subwoofer", v))
            button.pack(side="right", padx=3)
            self.controls.append(button)
            self.extra_controls.append(button)
        ttk.Label(sub_row, textvariable=self.sub_text).pack(side="right", padx=8)
        program_row = ttk.Frame(outer)
        program_row.pack(fill="x", pady=(0, 8))
        ttk.Label(program_row, text="声音模式").pack(side="left")
        for label, value in (("游戏", "game"), ("电影", "movie"), ("标准", "standard"), ("立体声", "stereo")):
            button = ttk.Button(program_row, text=label, width=6, command=lambda v=value: self.execute("program", v))
            button.pack(side="right", padx=2)
            self.controls.append(button)
            self.extra_controls.append(button)
        ttk.Label(outer, textvariable=self.program_text).pack(anchor="w")
        for key, title in (("three-d", "3D 环绕"), ("mute", "静音"), ("clear-voice", "Clear Voice"), ("bass-extension", "Bass Extension")):
            row = ttk.Frame(outer)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=title, style="Info.TLabel").pack(side="left")
            button = ttk.Button(row, text="--", command=lambda k=key: self.toggle(k))
            button.pack(side="right")
            self.buttons[key] = button
            self.controls.append(button)
            if key == "three-d":
                self.extra_controls.append(button)
        row = ttk.Frame(outer)
        row.pack(fill="x", pady=10)
        ttk.Label(row, text="指示灯", style="Info.TLabel").pack(side="left")
        for label, value in (("关闭", "off"), ("暗", "dim"), ("亮", "bright")):
            button = ttk.Radiobutton(row, text=label, value=value, variable=self.dimmer,
                                     command=lambda v=value: self.execute("dimmer", v))
            button.pack(side="right", padx=3)
            self.controls.append(button)
        ttk.Separator(outer).pack(fill="x", pady=(15, 10))
        ttk.Label(outer, textvariable=self.status_text, wraplength=430).pack(anchor="w")
        ttk.Label(outer, textvariable=self.detail_text, foreground="#666666", wraplength=430).pack(anchor="w", pady=(4, 0))
        self.set_busy(True)

    def show_advanced(self):
        window = tk.Toplevel(self.root)
        window.title("SR-B20A 高级设置指南")
        window.geometry("670x600")
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="遥控器与机身高级设置", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="以下需手动操作；本窗口不读取或更改这些设置。", wraplength=620).pack(anchor="w", pady=(0, 8))
        box = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10), relief="flat", padx=8, pady=8)
        scrollbar = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        box.pack(fill="both", expand=True)
        box.insert("1.0", ADVANCED_GUIDE)
        box.configure(state="disabled")
        ttk.Button(frame, text="打开 Yamaha 官方使用指南", command=lambda: webbrowser.open("https://manual.yamaha.com/av/20/srb20a/en-US/" )).pack(anchor="w", pady=(8, 0))

    def volume_changed(self, _=None):
        self.volume_text.set(f"{self.volume.get()} / 50")

    def set_busy(self, busy):
        self.busy = busy
        for widget in self.controls:
            widget.state(["disabled"] if busy or self.state is None else ["!disabled"])
        for widget in self.extra_controls:
            widget.state(["disabled"] if busy or self.state is None else ["!disabled"])
        if self.state is not None and self.state.get("program") == "stereo":
            self.buttons["three-d"].state(["disabled"])
        self.power_on.state(["disabled"] if busy else ["!disabled"])
        self.refresh.state(["disabled"] if busy else ["!disabled"])
        self.mode_box.configure(state="disabled" if busy else "readonly")

    def mode_changed(self, _event=None):
        self.state = None
        self.state_text.set("等待状态")
        self.execute("status")

    def toggle(self, key):
        field = {"mute": "mute", "clear-voice": "clear_voice_bit", "bass-extension": "bass_extension_bit", "three-d": "three_d"}[key]
        if self.state is not None:
            self.execute(key, "off" if self.state[field] else "on")

    def execute(self, command, value=None):
        if self.busy and not (command == "status" and self.state is None):
            return
        self.set_busy(True)
        self.status_text.set("正在连接音箱，请稍候…")
        self.detail_text.set("每次操作会读取设备状态并确认结果")
        mode = self.mode.get()
        def work():
            try:
                if mode == "本机蓝牙" and command in ("subwoofer", "program", "three-d"):
                    from sr_b20a_extra import run_extended
                    result = asyncio.run(run_extended(command, value))
                    error = None if result.get("ok") else failure_message(result, "操作未确认")
                else:
                    result, error = direct(command, value) if mode == "本机蓝牙" else gateway(command, value)
            except Exception as exc:
                result, error = None, str(exc)
            self.events.put((command, result, error))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                command, result, error = self.events.get_nowait()
                if error:
                    self.state = None
                    self.state_text.set("状态未知")
                    self.status_text.set("操作未确认：" + error)
                    self.detail_text.set("请先刷新状态，确认结果后再操作。")
                else:
                    self.state = result.get("after") or result.get("before")
                    if self.state:
                        from sr_b20a_extra import extra_state
                        extra_state(self.state)
                    if self.state:
                        self.render_state()
                    self.status_text.set("状态已更新" if command == "status" else "操作已确认")
                    self.detail_text.set("本机蓝牙直连" if self.mode.get() == "本机蓝牙" else "请求 ID：" + result.get("gateway", {}).get("request_id", "--"))
                self.set_busy(False)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def render_state(self):
        state = self.state
        self.state_text.set(f"{'开机' if state['power'] else '待机'}  ·  输入：{state.get('input', '--')}")
        self.volume.set(state["volume_raw"])
        self.input.set(state.get("input") or "")
        sub = state['subwoofer_raw']
        self.sub_text.set(str((sub - 16) // 4) if sub in range(0, 33, 4) else f"原始值 {sub}")
        names = {'stereo': '立体声', 'standard': '标准', 'movie': '电影', 'game': '游戏'}
        self.program_text.set('当前模式：' + names.get(state.get('program'), '未知'))
        self.volume_changed()
        for key, field in (("three-d", "three_d"), ("mute", "mute"), ("clear-voice", "clear_voice_bit"), ("bass-extension", "bass_extension_bit")):
            self.buttons[key].configure(text="开启" if state[field] else "关闭")
        self.dimmer.set(state.get("dimmer", ""))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        direct_result, direct_error = direct("status")
        gateway_result, gateway_error = gateway("status")
        Path(sys.argv[2]).write_text(json.dumps({"direct_ok": bool(direct_result), "direct_error": direct_error,
                                               "gateway_ok": bool(gateway_result), "gateway_error": gateway_error},
                                              ensure_ascii=False), encoding="utf-8")
    else:
        root = tk.Tk()
        root.withdraw()
        try:
            get_address()
        except ValueError:
            from srb20a_discovery import discover_soundbars
            root.deiconify()
            root.title("正在搜索音箱")
            progress = ttk.Label(root, text="正在搜索附近的雅马哈音箱，请稍候…", padding=24)
            progress.pack()
            root.update()
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    candidates = pool.submit(lambda: asyncio.run(discover_soundbars())).result()
            except Exception:
                candidates = []
            progress.destroy()
            root.withdraw()
            if len(candidates) == 1:
                save_address(candidates[0][0])
            else:
                listing = "\n".join(f"{i + 1}. {name} ({address})" for i, (address, name) in enumerate(candidates))
                prompt = ("发现多台设备，请输入序号：\n" + listing if candidates
                          else "未找到音箱。请输入蓝牙地址，例如 00:11:22:33:44:55：")
                while True:
                    value = simpledialog.askstring("选择音箱", prompt, parent=root)
                    if value is None:
                        root.destroy()
                        sys.exit(0)
                    try:
                        if candidates:
                            index = int(value) - 1
                            if not 0 <= index < len(candidates):
                                raise ValueError("请选择有效序号")
                            value = candidates[index][0]
                        save_address(value)
                        break
                    except ValueError as exc:
                        messagebox.showerror("地址无效", str(exc), parent=root)
        root.deiconify()
        App(root)
        root.mainloop()
