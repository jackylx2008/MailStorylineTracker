from __future__ import annotations

import logging
import tempfile
import tkinter as tk
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from mail_storyline_tracker.config import AppContext
from mail_storyline_tracker.gui.app import MailStorylineApp


class GuiLayoutTests(unittest.TestCase):
    def test_target_inputs_are_in_first_tab_and_feed_target_scan(self) -> None:
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
                self.assertTrue(all(str(editor).startswith(str(first_tab)) for editor in app.target_inputs.values()))
                self.assertEqual(app.variables["senders"].get(), "alice@example.com")
                self.assertEqual(app.variables["recipients"].get(), "alice@example.com")
                self.assertEqual(app.variables["keywords"].get(), "审核")
                app._apply_targets_to_search()
                self.assertIn("alice@example.com", app.variables["senders"].get())
                self.assertIn("alice@example.com", app.variables["recipients"].get())
                self.assertIn("审核", app.variables["keywords"].get())
                app.variables["since"].set("2025-01-01")
                queued = []
                app._run = lambda _title, operation: queued.append(operation)
                with patch("mail_storyline_tracker.gui.app.scan_targets", return_value={}) as scan:
                    app._start_target_scan()
                    queued[0]()
                self.assertEqual(scan.call_args.args[3]["since"], "2025-01-01")
                app.cancel_event.set()
                with self.assertRaises(CancelledError):
                    app._progress_callback("INBOX UID 1", 1, 1)
                app.events.put(("result", {"cancelled": True, "incomplete": True}))
                app.events.put(("finished", None))
                app._poll()
                self.assertEqual(app.status.get(), "已取消")
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
