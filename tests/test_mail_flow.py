from __future__ import annotations

import tempfile
import unittest
import imaplib
from concurrent.futures import CancelledError
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from mail_storyline_tracker.config import AppContext
from mail_storyline_tracker.flows.mail_flow import analyze, check_login, download, preview
from mail_storyline_tracker.modules.mail_parser import parse_message
from mail_storyline_tracker.modules.storage import ArchiveStore


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
    def fetch_message(self, uid: str):
        if uid == "1":
            raise imaplib.IMAP4.abort("socket closed")
        return super().fetch_message(uid)

    def fetch_message_preview(self, uid: str, max_bytes: int):
        if uid == "1":
            raise imaplib.IMAP4.abort("socket closed")
        return super().fetch_message_preview(uid, max_bytes)


class DirectDownloadFakeImapClient(PagedFakeImapClient):
    preview_calls = 0
    full_calls = 0

    def fetch_message(self, uid: str):
        type(self).full_calls += 1
        return super().fetch_message(uid)

    def fetch_message_preview(self, uid: str, max_bytes: int):
        type(self).preview_calls += 1
        return super().fetch_message_preview(uid, max_bytes)


class MailFlowTests(unittest.TestCase):
    def test_user_cancel_is_clean_and_keeps_download_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"match_mode": "any"},
                },
            })

            def cancel_on_second(label: str, _done: int, _total: int) -> None:
                if "UID 1" in label:
                    raise CancelledError("任务已取消")

            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", PagedFakeImapClient), patch(
                "mail_storyline_tracker.flows.mail_flow.logger.exception"
            ) as log_exception:
                first = download(ctx, progress=cancel_on_second)
                resumed = download(ctx)
            self.assertTrue(first["cancelled"])
            self.assertTrue(first["incomplete"])
            self.assertEqual(first["messages_saved"], 1)
            self.assertEqual(first["errors"], [])
            self.assertIn("用户已取消", first["stop_reason"])
            self.assertEqual(resumed["messages_saved"], 1)
            log_exception.assert_not_called()

    def test_review_excluded_message_id_alias_never_gets_full_download(self) -> None:
        class AliasClient(FakeImapClient):
            preview_calls = 0
            full_calls = 0

            def search_filtered_uids(self, *args):
                return ["3"], {"3": ["主题/正文关键词"]}

            def fetch_message_preview(self, uid, max_bytes):
                type(self).preview_calls += 1
                return FakeImapClient.messages["1"][:max_bytes]

            def fetch_message(self, uid):
                type(self).full_calls += 1
                raise AssertionError("已排除邮件别名不应完整下载")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"keywords": ["验收"], "match_mode": "any"},
                },
            })
            store = ArchiveStore(ctx.data_dir)
            raw = FakeImapClient.messages["1"]
            record = parse_message(raw, account="demo@126.com", mailbox="archive", uidvalidity="7", uid="1")
            stored = store.save_message(raw, record)
            store.flush()
            store.update_review_exclusions({stored["record_id"]}, excluded=True)
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", AliasClient):
                first = download(ctx)
                second = download(ctx)
            self.assertEqual(AliasClient.preview_calls, 1)
            self.assertEqual(AliasClient.full_calls, 0)
            self.assertEqual(first["review_excluded_skipped"], 1)
            self.assertEqual(second["review_excluded_skipped"], 1)

    def test_review_excluded_source_is_never_fetched_again(self) -> None:
        class CountingClient(PagedFakeImapClient):
            fetched_uids: list[str] = []

            def fetch_message(self, uid: str):
                type(self).fetched_uids.append(uid)
                return super().fetch_message(uid)

            def fetch_message_preview(self, uid: str, max_bytes: int):
                type(self).fetched_uids.append(uid)
                return super().fetch_message_preview(uid, max_bytes)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"user": "demo@126.com", "password": "secret"},
                    "folders": ["INBOX"],
                    "filters": {"keywords": ["验收"], "match_mode": "any"},
                },
            }
            ctx = AppContext(root, config)
            store = ArchiveStore(ctx.data_dir)
            raw = FakeImapClient.messages["1"]
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="7", uid="1")
            stored = store.save_message(raw, record)
            store.flush()
            store.update_review_exclusions({stored["record_id"]}, excluded=True)
            CountingClient.fetched_uids = []
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", CountingClient):
                preview_result = preview(ctx)
                download_result = download(ctx, {"keywords": ["项目"]})
                direct_result = download(ctx, {"keywords": []})
            self.assertNotIn("1", CountingClient.fetched_uids)
            self.assertEqual(preview_result["review_excluded_skipped"], 1)
            self.assertEqual(download_result["review_excluded_skipped"], 1)
            self.assertEqual(direct_result["review_excluded_skipped"], 1)
            self.assertEqual(download_result["messages_saved"], 1)  # UID 2 contains the changed keyword.
            self.assertEqual(direct_result["local_full_reused"], 1)

    def test_ai_analysis_skips_review_excluded_mail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {"app": {"data_dir": "data", "output_dir": "output"}})
            raw = _message("alice@example.com", "示例审核", "请审核。", "<excluded@example.com>")
            store = ArchiveStore(ctx.data_dir)
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="1", uid="9")
            stored = store.save_message(raw, record)
            store.flush()
            store.update_review_exclusions({stored["record_id"]}, excluded=True)
            with patch("mail_storyline_tracker.flows.mail_flow.OpenAICompatibleClient") as ai_client:
                with self.assertRaisesRegex(RuntimeError, "尚无可分析邮件"):
                    analyze(ctx)
                ai_client.assert_not_called()

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

    def test_unfiltered_archive_uses_one_full_fetch_per_message(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["声学"],
                    "max_messages_per_folder": 1,
                    "max_messages_per_run": 1,
                    "filters": {"match_mode": "any"},
                },
            }
            DirectDownloadFakeImapClient.preview_calls = 0
            DirectDownloadFakeImapClient.full_calls = 0
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", DirectDownloadFakeImapClient):
                result = download(AppContext(root, config))
            self.assertEqual(result["messages_saved"], 1)
            self.assertEqual(DirectDownloadFakeImapClient.preview_calls, 0)
            self.assertEqual(DirectDownloadFakeImapClient.full_calls, 1)

    def test_address_queue_reuses_full_mail_from_folder_archive(self) -> None:
        class AddressReuseFakeImapClient(DirectDownloadFakeImapClient):
            def __init__(self, settings) -> None:
                super().__init__(settings)
                self.address_filtered = bool(settings.senders or settings.recipients)

            def search_filtered_uids(self, since, before, maximum, senders, recipients, keywords, match_mode):
                if self.address_filtered:
                    return ["2"], {"2": ["发件人"]}
                return super().search_filtered_uids(since, before, maximum, senders, recipients, keywords, match_mode)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {
                    "imap": {"host": "imap.126.com", "port": 993, "user": "demo@126.com", "password": "secret"},
                    "folders": ["声学"],
                    "max_messages_per_folder": 1,
                    "max_messages_per_run": 1,
                    "filters": {"match_mode": "any"},
                },
            }
            ctx = AppContext(root, config)
            AddressReuseFakeImapClient.preview_calls = 0
            AddressReuseFakeImapClient.full_calls = 0
            with patch("mail_storyline_tracker.flows.mail_flow.Imap126Client", AddressReuseFakeImapClient):
                download(ctx)
                address_result = download(ctx, {"senders": ["news@example.com"]})
            self.assertEqual(AddressReuseFakeImapClient.full_calls, 1)
            self.assertEqual(address_result["local_full_reused"], 1)

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
