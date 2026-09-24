from __future__ import annotations

import tempfile
import unittest
import imaplib
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from mail_storyline_tracker.config import AppContext
from mail_storyline_tracker.flows.mail_flow import check_login, download, preview


def _message(sender: str, subject: str, body: str, message_id: str) -> bytes:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "team@example.com"
    message["Subject"] = subject
    message["Date"] = "Wed, 23 Sep 2026 09:00:00 +0800"
    message["Message-ID"] = message_id
    message.set_content(body)
    return message.as_bytes()


class FakeImapClient:
    messages = {
        "2": _message("news@example.com", "普通新闻", "与项目无关", "<two@example.com>"),
        "1": _message("owner@example.com", "示例项目验收", "请完成验收", "<one@example.com>"),
    }

    def __init__(self, settings) -> None:
        self.uidvalidity = "7"

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def select_mailbox(self, mailbox: str):
        return len(self.messages), self.uidvalidity

    def search_uids(self, since: str, before: str, maximum: int):
        return list(self.messages)

    def search_filtered_uids(self, since, before, maximum, senders, recipients, keywords, match_mode):
        return ["1"], {"1": ["主题/正文关键词"]}

    def fetch_message(self, uid: str):
        return self.messages[uid]

    def fetch_message_preview(self, uid: str, max_bytes: int):
        return self.messages[uid][:max_bytes]


class PagedFakeImapClient(FakeImapClient):
    def search_filtered_uids(self, since, before, maximum, senders, recipients, keywords, match_mode):
        return ["2", "1"], {"2": [], "1": []}


class DisconnectingFakeImapClient(PagedFakeImapClient):
    def fetch_message_preview(self, uid: str, max_bytes: int):
        if uid == "1":
            raise imaplib.IMAP4.abort("socket closed")
        return super().fetch_message_preview(uid, max_bytes)


class MailFlowTests(unittest.TestCase):
    def test_login_check_does_not_select_or_fetch_mail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"match_mode": "any"},
                },
            }
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", FakeImapClient):
                result = check_login(AppContext(root, config))
            self.assertEqual(result["status"], "ok")
            self.assertFalse(result["mail_accessed"])

    def test_download_archives_matches_and_skips_processed_uids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "since": "2026-01-01",
                    "before": "",
                    "max_messages_per_folder": 100,
                    "filters": {"senders": [], "recipients": [], "keywords": ["验收"], "match_mode": "any"},
                },
            }
            ctx = AppContext(root, config)
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", FakeImapClient):
                first = download(ctx)
                second = download(ctx)
            self.assertEqual(first["messages_checked"], 1)
            self.assertEqual(first["messages_matched"], 1)
            self.assertEqual(first["messages_saved"], 1)
            self.assertEqual(second["messages_checked"], 0)
            self.assertEqual(second["incremental_skipped"], 1)
            self.assertTrue((root / "output" / "mail_review.html").exists())
            self.assertEqual(len(list((root / "data" / "raw_mail" / "INBOX" / "eml").glob("*.eml"))), 1)

    def test_preview_uses_server_candidates_and_partial_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"keywords": ["验收"], "match_mode": "any"},
                },
            }
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", FakeImapClient):
                result = preview(AppContext(root, config))
            self.assertEqual(result["messages_checked"], 1)
            self.assertEqual(result["messages_matched"], 1)
            self.assertFalse(result["incomplete"])

    def test_download_advances_past_processed_latest_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "max_messages_per_folder": 1,
                    "filters": {"match_mode": "any"},
                },
            }
            ctx = AppContext(root, config)
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", PagedFakeImapClient):
                first = download(ctx)
                second = download(ctx)
            self.assertEqual(first["messages_saved"], 1)
            self.assertEqual(second["messages_saved"], 1)
            self.assertEqual(len(list((root / "data" / "raw_mail" / "INBOX" / "eml").glob("*.eml"))), 2)

    def test_global_run_budget_stops_safely_across_folders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX", "archive"],
                    "max_messages_per_folder": 50,
                    "max_messages_per_run": 1,
                    "filters": {"match_mode": "any"},
                },
            }
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", PagedFakeImapClient):
                result = download(AppContext(root, config))
            self.assertEqual(result["messages_checked"], 1)
            self.assertTrue(result["incomplete"])
            self.assertIn("单次运行保守上限", result["stop_reason"])

    def test_connection_abort_stops_and_keeps_completed_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"match_mode": "any"},
                },
            }
            ctx = AppContext(root, config)
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", DisconnectingFakeImapClient):
                first = download(ctx)
                second = download(ctx)
            self.assertTrue(first["incomplete"])
            self.assertIn("断点续传", first["stop_reason"])
            self.assertEqual(second["incremental_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
