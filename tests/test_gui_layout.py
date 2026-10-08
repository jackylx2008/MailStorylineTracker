from __future__ import annotations

import logging
import tempfile
import tkinter as tk
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
from tkinter import ttk
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from mail_storyline_tracker.config import AppContext
from mail_storyline_tracker.gui.app import MailStorylineApp


class GuiLayoutTests(unittest.TestCase):
    def test_manual_final_keyword_is_in_ai_tab_and_uses_reviewed_mail(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"当前环境没有图形显示：{exc}")
        root.withdraw()
        old_handlers = set(logging.getLogger().handlers)
        try:
            with tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                (project / "target_email.env").write_text("alice@example.com\n", encoding="utf-8")
                (project / "target_keyword.env").write_text("审核\n", encoding="utf-8")
                (project / "target_file.env").write_text("示例事项\n", encoding="utf-8")
                ctx = AppContext(project, {"app": {"data_dir": "data", "output_dir": "output"}})
                app = MailStorylineApp(root, ctx)
                notebook = next(child for child in root.winfo_children() if isinstance(child, ttk.Notebook))
                self.assertEqual(
                    [notebook.tab(tab, "text") for tab in notebook.tabs()],
                    ["邮箱连接与筛选", "下载与归档", "AI 梳理与时间线", "全局配置"],
                )
                first_tab = notebook.nametowidget(notebook.tabs()[0])
                ai_tab = notebook.nametowidget(notebook.tabs()[2])

                def button_labels(widget: tk.Misc) -> list[str]:
                    children = widget.winfo_children()
                    return [child.cget("text") for child in children if isinstance(child, ttk.Button)] + [
                        label for child in children for label in button_labels(child)
                    ]

                self.assertIn("从人工保留邮件生成并审核事件链", button_labels(ai_tab))
                self.assertIn("按关键词生成事项时间线（本地 AI）", button_labels(ai_tab))
                self.assertNotIn("生成事项时间线", button_labels(ai_tab))
                self.assertIn("按 target_*.env 专项扫描", button_labels(first_tab))
                self.assertNotIn("按 target_*.env 专项扫描", button_labels(ai_tab))
                self.assertNotIn("从人工保留邮件生成并审核事件链", button_labels(first_tab))
                self.assertEqual(app.variables["senders"].get(), "alice@example.com")
                self.assertEqual(app.variables["recipients"].get(), "alice@example.com")
                self.assertEqual(app.variables["keywords"].get(), "审核")
                with self.assertRaises(ValueError):
                    app._target_criteria()
                app.final_file_keyword.set("review")
                self.assertEqual(app._target_criteria().files, ("review",))
                app.variables["since"].set("2025-01-01")
                queued = []
                app._run = lambda _title, operation: queued.append(operation)
                with patch("mail_storyline_tracker.gui.app.analyze", return_value={}) as analyze:
                    app._start_keyword_analysis()
                    queued.pop()()
                self.assertEqual(analyze.call_args.kwargs["final_file_keyword"], "review")
                with patch("mail_storyline_tracker.gui.app.scan_targets", return_value={}) as scan:
                    app._start_target_scan()
                    queued[0]()
                self.assertEqual(scan.call_args.args[3]["since"], "2025-01-01")
                self.assertEqual(scan.call_args.args[2].files, ("示例事项",))
                app.cancel_event.set()
                with self.assertRaises(CancelledError):
                    app._progress_callback("INBOX UID 1", 1, 1)
                app.events.put(("result", {"cancelled": True, "incomplete": True}))
                app.events.put(("finished", None))
                app._poll()
                self.assertEqual(app.status.get(), "已取消")
                with patch("mail_storyline_tracker.gui.app.webbrowser.open") as open_browser:
                    app._open_review()
                opened = open_browser.call_args.args[0]
                self.assertEqual(opened, app.review_service.page_url)
                with patch("mail_storyline_tracker.gui.app.webbrowser.open") as open_browser:
                    app._open_review(import_legacy=True)
                opened = open_browser.call_args.args[0]
                self.assertTrue(opened.startswith("file:"))
                self.assertEqual(parse_qs(urlsplit(opened).query)["review_page"][0], app.review_service.page_url)
                with patch("mail_storyline_tracker.gui.app.webbrowser.open") as open_browser:
                    app._open_target_storyline()
                self.assertEqual(open_browser.call_args.args[0], app.review_service.storyline_url)
                self.assertTrue((ctx.output_dir / "target_storylines.html").exists())
                self.assertEqual(app.active_target_criteria.files, ("review",))
                self.assertTrue(app.active_filename_only)
                app.review_service.close()
                app.status.set("运行")
                app.events.put(("result", {"summary": {"cancelled": True}}))
                app.events.put(("finished", None))
                app._poll()
                self.assertEqual(app.status.get(), "已取消")
        finally:
            for handler in set(logging.getLogger().handlers) - old_handlers:
                logging.getLogger().removeHandler(handler)
            root.destroy()


if __name__ == "__main__":
    unittest.main()
