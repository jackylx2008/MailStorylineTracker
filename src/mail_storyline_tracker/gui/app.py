from __future__ import annotations

import json
import logging
import queue
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import messagebox, ttk

from ..config import AppContext
from ..flows.mail_flow import analyze, check_ai, check_connection, download, list_folders, preview
from ..flows.target_flow import scan_targets
from ..modules.ai_client import AISettings
from ..modules.mail_settings import MailSettings
from ..modules.target_config import TargetCriteria


class QueueHandler(logging.Handler):
    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        super().__init__()
        self.events = events

    def emit(self, record: logging.LogRecord) -> None:
        self.events.put(("log", self.format(record)))


class MailStorylineApp:
    def __init__(self, root: tk.Tk, ctx: AppContext) -> None:
        self.root = root
        self.ctx = ctx
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.started_at = 0.0
        self.last_html = ""
        self.variables: dict[str, tk.Variable] = {}
        self.action_buttons: list[ttk.Button] = []
        self.status = tk.StringVar(value="就绪")
        self.current = tk.StringVar(value="")
        self.elapsed = tk.StringVar(value="00:00:00")
        self.progress = tk.DoubleVar(value=0)
        self._configure_window()
        self._build()
        self._attach_logging()
        self.root.after(100, self._poll)

    def _configure_window(self) -> None:
        self.root.title("Mail Storyline Tracker")
        self.root.geometry("1120x780")
        self.root.minsize(900, 650)

    def _build(self) -> None:
        self.root.rowconfigure(0, weight=3)
        self.root.rowconfigure(1, weight=2)
        self.root.columnconfigure(0, weight=1)
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
        self._build_search_tab(notebook)
        self._build_archive_tab(notebook)
        self._build_target_tab(notebook)
        self._build_ai_tab(notebook)
        self._build_config_tab(notebook)

        log_frame = ttk.LabelFrame(self.root, text="运行日志与实时输出")
        log_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=12, state="disabled", wrap="word", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=8)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        ttk.Button(log_frame, text="清空界面日志", command=self._clear_log).grid(row=1, column=0, sticky="e", padx=8, pady=(0, 6))

        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(2, 10))
        status_frame.columnconfigure(0, weight=1)
        ttk.Progressbar(status_frame, variable=self.progress, maximum=100).grid(row=0, column=0, columnspan=4, sticky="ew")
        ttk.Label(status_frame, textvariable=self.status).grid(row=1, column=0, sticky="w")
        ttk.Label(status_frame, textvariable=self.current).grid(row=1, column=1)
        ttk.Label(status_frame, textvariable=self.elapsed).grid(row=1, column=2, padx=12)
        self.cancel_button = ttk.Button(status_frame, text="取消任务", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=1, column=3, sticky="e")

    def _build_search_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=14)
        notebook.add(tab, text="邮箱连接与筛选")
        settings = MailSettings.from_config(self.ctx.config)
        fields = (
            ("folders", "邮箱文件夹（逗号分隔）", ",".join(settings.folders)),
            ("senders", "发件人地址/片段", ",".join(settings.senders)),
            ("recipients", "收件人/Cc 地址/片段", ",".join(settings.recipients)),
            ("keywords", "主题/正文关键词", ",".join(settings.keywords)),
            ("since", "起始日期", settings.since),
            ("before", "结束日期（不含，可留空）", settings.before),
        )
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky="w", padx=5, pady=6)
            variable = tk.StringVar(value=default)
            self.variables[key] = variable
            ttk.Entry(tab, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=5, pady=6)
        ttk.Label(tab, text="匹配方式").grid(row=6, column=0, sticky="w", padx=5, pady=6)
        mode = tk.StringVar(value=settings.match_mode)
        self.variables["match_mode"] = mode
        ttk.Combobox(tab, textvariable=mode, values=("any", "all"), state="readonly").grid(row=6, column=1, sticky="ew", padx=5, pady=6)
        tab.columnconfigure(1, weight=1)
        buttons = ttk.Frame(tab)
        buttons.grid(row=7, column=0, columnspan=2, sticky="ew", pady=14)
        self._button(buttons, "检查连接", lambda: self._run("检查邮箱连接", lambda: check_connection(self.ctx, self._overrides()))).pack(side="left", padx=4)
        self._button(buttons, "列出文件夹", lambda: self._run("读取邮箱文件夹", lambda: {"folders": list_folders(self.ctx)})).pack(side="left", padx=4)
        self._button(buttons, "筛选预览", lambda: self._run("筛选预览", lambda: preview(self.ctx, self._overrides(), self._progress_callback))).pack(side="left", padx=4)

    def _build_archive_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=14)
        notebook.add(tab, text="下载与归档")
        ttk.Label(tab, text="增量状态使用 UIDVALIDITY + UID、Message-ID 和内容哈希记录在本地 JSON。不会删除或修改服务器邮件。", wraplength=850).pack(anchor="w", pady=12)
        ttk.Label(tab, text=f"本地数据目录：{self.ctx.data_dir}").pack(anchor="w", pady=5)
        ttk.Label(tab, text=f"审核页面：{self.ctx.output_dir / 'mail_review.html'}").pack(anchor="w", pady=5)
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=18)
        self._button(row, "开始增量下载", lambda: self._run("增量下载", lambda: download(self.ctx, self._overrides(), self._progress_callback))).pack(side="left", padx=4)
        ttk.Button(row, text="打开邮件审核页", command=lambda: self._open(self.ctx.output_dir / "mail_review.html")).pack(side="left", padx=4)

    def _build_ai_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=14)
        notebook.add(tab, text="AI 梳理与时间线")
        settings = AISettings.from_config(self.ctx.config)
        ttk.Label(tab, text="仅连接已运行的 OpenAI 兼容服务；本项目不会启动或关闭 llama-server。", wraplength=850).pack(anchor="w", pady=10)
        ttk.Label(tab, text=f"服务：{settings.base_url}").pack(anchor="w", pady=4)
        ttk.Label(tab, text=f"模型：{settings.model}").pack(anchor="w", pady=4)
        ttk.Label(tab, text=f"远端发送：{'已启用' if settings.remote_enabled else '关闭（仅允许回环地址）'}").pack(anchor="w", pady=4)
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=18)
        self._button(row, "检查 AI 服务", lambda: self._run("检查 AI 服务", lambda: check_ai(self.ctx))).pack(side="left", padx=4)
        self._button(row, "生成事项时间线", lambda: self._run("AI 梳理", lambda: analyze(self.ctx))).pack(side="left", padx=4)
        ttk.Button(row, text="打开时间线页面", command=lambda: self._open(self.ctx.output_dir / "storyline.html")).pack(side="left", padx=4)

    def _build_target_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=14)
        notebook.add(tab, text="目标附件链路")
        try:
            criteria = TargetCriteria.load(self.ctx.project_root)
            summary = f"目标联系人 {len(criteria.emails)} 个 · 关键词 {len(criteria.keywords)} 个 · 独立附件事项 {len(criteria.files)} 个"
        except Exception as exc:
            summary = f"目标配置尚未就绪：{exc}"
        ttk.Label(tab, text=summary, wraplength=850).pack(anchor="w", pady=10)
        ttk.Label(
            tab,
            text="扫描登录账号下全部可选择文件夹；联系人、关键词、附件名任一命中即归档。附件名由本地 AI 模糊匹配，不读取附件正文。",
            wraplength=850,
        ).pack(anchor="w", pady=5)
        ttk.Label(tab, text=f"思维导图式结果：{self.ctx.output_dir / 'target_storylines.html'}").pack(anchor="w", pady=5)
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=18)
        self._button(row, "扫描并生成沟通链路", lambda: self._run("目标附件链路", lambda: scan_targets(self.ctx, self._progress_callback))).pack(side="left", padx=4)
        ttk.Button(row, text="打开沟通链路页面", command=lambda: self._open(self.ctx.output_dir / "target_storylines.html")).pack(side="left", padx=4)

    def _build_config_tab(self, notebook: ttk.Notebook) -> None:
        tab = ttk.Frame(notebook, padding=14)
        notebook.add(tab, text="全局配置")
        settings = MailSettings.from_config(self.ctx.config)
        text = (
            f"配置文件：{self.ctx.project_root / 'config.yaml'}\n"
            f"本地凭据：{self.ctx.project_root / '.env'}（也兼容 common.env）\n"
            f"邮箱账号：{_mask_email(settings.user)}\n"
            f"数据目录：{self.ctx.data_dir}\n输出目录：{self.ctx.output_dir}\n日志目录：{self.ctx.project_root / 'logs'}"
        )
        ttk.Label(tab, text=text, justify="left").pack(anchor="w", pady=10)

    def _button(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> ttk.Button:
        button = ttk.Button(parent, text=text, command=command)
        self.action_buttons.append(button)
        return button

    def _overrides(self) -> dict[str, Any]:
        return {key: variable.get() for key, variable in self.variables.items()}

    def _progress_callback(self, label: str, done: int, total: int) -> None:
        if self.cancel_event.is_set():
            raise RuntimeError("任务已取消")
        self.events.put(("progress", (label, done, total)))

    def _run(self, title: str, operation: Callable[[], Any]) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("任务运行中", "同一时间只能运行一个任务。")
            return
        self.cancel_event.clear()
        self.started_at = time.monotonic()
        self.status.set("运行")
        self.current.set(title)
        self.progress.set(0)
        self._set_running(True)

        def target() -> None:
            try:
                self.events.put(("result", operation()))
            except Exception as exc:
                self.events.put(("error", f"{type(exc).__name__}: {exc}"))
            finally:
                self.events.put(("finished", None))

        self.worker = threading.Thread(target=target, daemon=True, name="mail-storyline-task")
        self.worker.start()

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.status.set("正在取消")
        self._append_log("已请求取消；当前网络操作结束后停止。")

    def _set_running(self, running: bool) -> None:
        for button in self.action_buttons:
            button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "progress":
                    label, done, total = payload
                    self.current.set(label)
                    self.progress.set((done / total * 100) if total else 0)
                elif kind == "result":
                    self._append_log(json.dumps(payload, ensure_ascii=False, indent=2)[:12000])
                    if isinstance(payload, dict):
                        self.last_html = str(payload.get("html") or payload.get("review_html") or "")
                elif kind == "error":
                    self.status.set("已取消" if "任务已取消" in str(payload) else "失败")
                    self._append_log(str(payload))
                    if "任务已取消" not in str(payload):
                        messagebox.showerror("任务失败", str(payload))
                elif kind == "finished":
                    if self.status.get() not in {"失败", "已取消"}:
                        self.status.set("完成")
                    self.progress.set(100 if self.status.get() == "完成" else self.progress.get())
                    self._set_running(False)
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive():
            seconds = int(time.monotonic() - self.started_at)
            self.elapsed.set(f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}")
        self.root.after(100, self._poll)

    def _attach_logging(self) -> None:
        handler = QueueHandler(self.events)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)

    def _append_log(self, value: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", value + "\n")
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > 3000:
            self.log_text.delete("1.0", f"{line_count - 2500}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _open(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("文件不存在", f"尚未生成：{path}")
            return
        webbrowser.open(path.resolve().as_uri())


def run(root: tk.Tk, ctx: AppContext) -> None:
    MailStorylineApp(root, ctx)
    root.mainloop()


def _mask_email(value: str) -> str:
    if "@" not in value:
        return "未配置"
    local, domain = value.split("@", 1)
    return f"{local[:2]}***@{domain}"
