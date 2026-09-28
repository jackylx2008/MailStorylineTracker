from __future__ import annotations

import tempfile
import unittest
import json
from email.message import EmailMessage
from pathlib import Path
from urllib.request import Request, urlopen

from mail_storyline_tracker.modules.html_report import write_mail_review
from mail_storyline_tracker.modules.mail_parser import parse_message
from mail_storyline_tracker.modules.review_service import ReviewService
from mail_storyline_tracker.modules.storage import ArchiveStore


class MailReviewTests(unittest.TestCase):
    def test_browser_review_decision_persists_without_deleting_archive(self) -> None:
        message = EmailMessage()
        message["From"] = "alice@example.com"
        message["To"] = "team@example.com"
        message["Subject"] = "示例审核"
        message["Message-ID"] = "<review-example@example.com>"
        message.set_content("请审核。")
        raw = message.as_bytes()
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            store = ArchiveStore(data_dir)
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="1", uid="7")
            stored = store.save_message(raw, record)
            store.flush()
            rebuilds: list[bool] = []
            service = ReviewService(data_dir, lambda: rebuilds.append(True))
            try:
                preflight = Request(
                    service.url,
                    method="OPTIONS",
                    headers={"Origin": "null", "Access-Control-Request-Private-Network": "true"},
                )
                with urlopen(preflight, timeout=5) as response:
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"], "null")
                    self.assertEqual(response.headers["Access-Control-Allow-Private-Network"], "true")

                def request(action: str) -> dict:
                    payload = json.dumps({"action": action, "record_ids": [stored["record_id"]]}).encode("utf-8")
                    call = Request(service.url, data=payload, headers={"Origin": "null", "Content-Type": "application/json"})
                    with urlopen(call, timeout=5) as response:
                        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "null")
                        return json.load(response)

                excluded = request("merge")
                self.assertIn(stored["record_id"], excluded["excluded_record_ids"])
                self.assertFalse(excluded["report_error"])
                self.assertEqual(ArchiveStore(data_dir).reviewed_records(), [])
                self.assertTrue(Path(stored["eml_path"]).is_file())
                restored = request("restore")
                self.assertEqual(restored["excluded_record_ids"], [])
                self.assertEqual(len(ArchiveStore(data_dir).reviewed_records()), 1)
                self.assertEqual(len(rebuilds), 2)
            finally:
                service.close()

    def test_review_filters_index_all_addresses_and_full_body(self) -> None:
        record = {
            "record_id": "sample-1",
            "sent_at": "2026-09-28T09:00:00+08:00",
            "from": "Alice <alice@example.com>",
            "to": "Team <team@example.com>",
            "cc": "Reviewer <reviewer@example.com>",
            "addresses": {"from": ["alice@example.com"], "to": ["team@example.com"], "cc": ["reviewer@example.com"]},
            "subject": "审核资料",
            "body_text": "正文" * 1600 + "检索词",
            "attachments": [{"filename": "review.pdf"}],
            "matched_by": ["目标联系人"],
            "eml_path": "sample.eml",
        }
        with tempfile.TemporaryDirectory() as directory:
            page = write_mail_review([record], Path(directory) / "review.html").read_text(encoding="utf-8")
        self.assertIn('id="email-filter"', page)
        self.assertIn('id="keyword-filter"', page)
        self.assertIn('data-record-id="sample-1"', page)
        self.assertIn("reviewer@example.com", page)
        self.assertIn("检索词", page)
        self.assertIn("review.pdf", page)
        self.assertIn('class="delete-review"', page)
        self.assertIn('id="undo-delete"', page)
        self.assertIn("localStorage.setItem", page)
        self.assertIn("sendDecision('merge',[...deleted])", page)


if __name__ == "__main__":
    unittest.main()
