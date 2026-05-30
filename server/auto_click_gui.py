import tkinter as tk
from tkinter import scrolledtext, messagebox
import threading
import asyncio
import schedule
import time
import logging
import json
import os
from datetime import datetime
from playwright.async_api import async_playwright
import pyautogui

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("auto_click")

TARGET_URL = "https://dsw-gateway-cn-hangzhou.data.aliyun.com/dsw-1922829/lab/workspaces/auto-p"
CLICK_INTERVAL_MINUTES = 20
CLICK_COUNT = 2

CONFIG_FILE = "click_positions.json"


class ClickRecorder:
    def __init__(self):
        self.recording = False
        self.click_positions = []
        self.root_overlay = None

    def start_recording(self, callback):
        self.recording = True
        self.click_positions = []
        self.callback = callback
        self._create_overlay()

    def _create_overlay(self):
        self.root_overlay = tk.Toplevel()
        self.root_overlay.attributes("-fullscreen", True)
        self.root_overlay.attributes("-alpha", 0.3)
        self.root_overlay.attributes("-topmost", True)
        self.root_overlay.configure(bg="gray")

        label = tk.Label(self.root_overlay, text="点击屏幕录制点击位置 (按 ESC 结束录制)",
                        font=("微软雅黑", 24), bg="black", fg="white", pady=20)
        label.place(x=0, y=0, relwidth=1)

        info_label = tk.Label(self.root_overlay, text=f"已录制: 0 次点击",
                             font=("微软雅黑", 16), bg="black", fg="yellow")
        info_label.place(x=0, y=80, relwidth=1)
        self.info_label = info_label

        self.root_overlay.bind("<Button-1>", self._on_click)
        self.root_overlay.bind("<Escape>", self._stop_recording)
        self.root_overlay.focus_force()

    def _on_click(self, event):
        if not self.recording:
            return

        x, y = pyautogui.position()
        self.click_positions.append({"x": x, "y": y})
        self.info_label.config(text=f"已录制: {len(self.click_positions)} 次点击 | 位置: ({x}, {y})")

    def _stop_recording(self, event=None):
        self.recording = False
        if self.root_overlay:
            self.root_overlay.destroy()
            self.root_overlay = None
        if self.callback:
            cb = self.callback
            self.callback = None
            cb(self.click_positions)

    def stop_and_save(self):
        self._stop_recording()
        return self.click_positions


class AutoClickApp:
    def __init__(self, root):
        self.root = root
        self.root.title("阿里云DSW自动点击器")
        self.root.geometry("650x550")
        self.root.resizable(True, True)

        self.running = False
        self.task_thread = None
        self.stop_event = threading.Event()
        self.recorder = ClickRecorder()

        self.click_positions = self.load_positions()

        self.setup_ui()
        self.update_position_count()

    def load_positions(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return []

    def save_positions(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.click_positions, f, indent=2)

    def setup_ui(self):
        title_label = tk.Label(self.root, text="阿里云DSW自动点击器", font=("微软雅黑", 16, "bold"))
        title_label.pack(pady=10)

        info_frame = tk.Frame(self.root)
        info_frame.pack(fill="x", padx=20, pady=5)
        tk.Label(info_frame, text=f"目标网址: {TARGET_URL}", font=("", 9)).pack(anchor="w")
        tk.Label(info_frame, text=f"执行间隔: 每{CLICK_INTERVAL_MINUTES}分钟", font=("", 9)).pack(anchor="w")
        tk.Label(info_frame, text=f"点击次数: {CLICK_COUNT}次", font=("", 9)).pack(anchor="w")
        self.position_count_label = tk.Label(info_frame, text="已保存点击位置: 0 个", font=("", 9), fg="blue")
        self.position_count_label.pack(anchor="w")

        self.status_label = tk.Label(self.root, text="状态: 已停止", font=("微软雅黑", 12), fg="red")
        self.status_label.pack(pady=10)

        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=10)

        self.record_btn = tk.Button(btn_frame, text="录制点击", font=("微软雅黑", 11), width=10,
                                    bg="#9C27B0", fg="white", command=self.start_recording)
        self.record_btn.pack(side="left", padx=5)

        self.clear_btn = tk.Button(btn_frame, text="清空位置", font=("微软雅黑", 11), width=10,
                                   bg="#FF9800", fg="white", command=self.clear_positions)
        self.clear_btn.pack(side="left", padx=5)

        self.test_btn = tk.Button(btn_frame, text="测试(立即执行)", font=("微软雅黑", 11), width=12,
                                  bg="#2196F3", fg="white", command=self.test_task)
        self.test_btn.pack(side="left", padx=5)

        control_frame = tk.Frame(self.root)
        control_frame.pack(pady=5)

        self.start_btn = tk.Button(control_frame, text="开始", font=("微软雅黑", 12), width=10,
                                   bg="#4CAF50", fg="white", command=self.start_task)
        self.start_btn.pack(side="left", padx=5)

        self.stop_btn = tk.Button(control_frame, text="停止", font=("微软雅黑", 12), width=10,
                                  bg="#f44336", fg="white", command=self.stop_task, state="disabled")
        self.stop_btn.pack(side="left", padx=5)

        tk.Label(self.root, text="执行日志:", font=("", 10)).pack(anchor="w", padx=20)

        self.log_text = scrolledtext.ScrolledText(self.root, font=("Consolas", 9),
                                                 width=75, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=20, pady=10)

        self.log("=" * 60)
        self.log("提示: 点击'录制点击'按钮后，在屏幕上点击要点击的位置")
        self.log("录制完成后按 ESC 退出录制模式")
        self.log("=" * 60)

    def update_position_count(self):
        self.position_count_label.config(text=f"已保存点击位置: {len(self.click_positions)} 个")

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def update_status(self, status, color):
        self.status_label.config(text=f"状态: {status}", fg=color)

    def start_recording(self):
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 开始录制点击位置...")
        self.record_btn.config(state="disabled")
        self.recorder.start_recording(self.on_record_complete)

    def on_record_complete(self, positions):
        self.record_btn.config(state="normal")
        if positions:
            self.click_positions = positions
            self.save_positions()
            self.update_position_count()
            self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 录制完成，已保存 {len(positions)} 个点击位置")
            for i, pos in enumerate(positions):
                self.log(f"  位置 {i+1}: ({pos['x']}, {pos['y']})")
        else:
            self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 录制被取消或没有点击")

    def clear_positions(self):
        self.click_positions = []
        self.save_positions()
        self.update_position_count()
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 已清空所有点击位置")

    def test_task(self):
        if not self.click_positions:
            messagebox.showwarning("警告", "请先录制点击位置！")
            return
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] [测试] 立即执行一次...")
        threading.Thread(target=self.execute_clicks, daemon=True).start()

    def start_task(self):
        if not self.click_positions:
            messagebox.showwarning("警告", "请先录制点击位置！")
            return
        if self.running:
            return

        self.running = True
        self.stop_event.clear()
        self.record_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.update_status("运行中", "green")
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 任务已启动")

        self.task_thread = threading.Thread(target=self.run_schedule_loop, daemon=True)
        self.task_thread.start()

    def stop_task(self):
        if not self.running:
            return

        self.running = False
        self.stop_event.set()
        self.record_btn.config(state="normal")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.update_status("已停止", "red")
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 任务已停止")

    def run_schedule_loop(self):
        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 执行首次任务...")

        self.execute_clicks()

        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 首次任务完成，设置定时器...")

        schedule.every(CLICK_INTERVAL_MINUTES).minutes.do(self.execute_clicks)

        while self.running and not self.stop_event.is_set():
            schedule.run_pending()

            next_run = schedule.next_run()
            if next_run:
                remaining = next_run - datetime.now()
                total_seconds = int(remaining.total_seconds())
                if total_seconds > 0:
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    self.status_label.config(text=f"下次执行: {minutes:02d}:{seconds:02d}", fg="blue")

            time.sleep(1)

    def execute_clicks(self):
        if not self.click_positions:
            return

        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 开始执行点击...")

        for i, pos in enumerate(self.click_positions):
            try:
                self.log(f"  [{i+1}/{len(self.click_positions)}] 3秒后点击 ({pos['x']}, {pos['y']})...")
                for countdown in range(3, 0, -1):
                    self.status_label.config(text=f"状态: 倒计时 {countdown}", fg="orange")
                    self.root.update()
                    time.sleep(1)
                pyautogui.click(pos['x'], pos['y'])
                self.log(f"  [OK] 点击 {i+1}/{len(self.click_positions)}: ({pos['x']}, {pos['y']})")
                time.sleep(0.3)
            except Exception as e:
                self.log(f"  [失败] {e}")

        self.log(f"[{datetime.now().strftime('%H:%M:%S')}] 执行完成")
        self.update_status("运行中", "green")


def main():
    root = tk.Tk()
    app = AutoClickApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
