from __future__ import annotations

import tempfile
import unittest
import json
import shutil
import subprocess
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from mail_storyline_tracker.modules.html_report import REVIEW_SCRIPT, write_mail_review
from mail_storyline_tracker.modules.mail_parser import parse_message
from mail_storyline_tracker.modules.review_service import ReviewService
from mail_storyline_tracker.modules.storage import ArchiveStore


class MailReviewTests(unittest.TestCase):
    def test_batch_save_is_atomic_and_updates_future_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            store = ArchiveStore(data_dir)
            ids = []
            for number in (1, 2):
                message = EmailMessage()
                message["Message-ID"] = f"<batch-{number}@example.com>"
                message.set_content("Synthetic message")
                raw = message.as_bytes()
                record = parse_message(raw, account="test@126.com", mailbox="INBOX", uidvalidity="1", uid=str(number))
                ids.append(store.save_message(raw, record)["record_id"])
            store.flush()
            rebuilt = []
            service = ReviewService(data_dir, lambda: rebuilt.append(True))
            try:
                def save(exclude_ids: list[str], restore_ids: list[str]) -> dict:
                    body = json.dumps({"action": "save", "exclude_ids": exclude_ids, "restore_ids": restore_ids}).encode()
                    with urlopen(Request(service.url, data=body, headers={"Content-Type": "application/json"}), timeout=5) as response:
                        return json.load(response)

                self.assertEqual(set(save(ids, [])["excluded_record_ids"]), set(ids))
                self.assertEqual(ArchiveStore(data_dir).reviewed_records(), [])
                self.assertEqual(save([], [ids[0]])["excluded_record_ids"], [ids[1]])
                with self.assertRaises(HTTPError) as invalid:
                    save([ids[0], "unknown-id"], [])
                self.assertEqual(invalid.exception.code, 400)
                self.assertEqual(ArchiveStore(data_dir).excluded_record_ids(), {ids[1]})
                self.assertEqual(len(rebuilt), 2)
            finally:
                service.close()

    @unittest.skipUnless(shutil.which("node"), "JavaScript runtime is unavailable")
    def test_real_script_immediate_delete_and_backend_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            store = ArchiveStore(data_dir)
            ids = []
            for number in (1, 2):
                message = EmailMessage()
                message["Message-ID"] = f"<click-{number}@example.com>"
                message["Subject"] = "Synthetic review fixture"
                message.set_content("Test mail")
                raw = message.as_bytes()
                record = parse_message(raw, account="test@126.com", mailbox="INBOX", uidvalidity="1", uid=str(number))
                ids.append(store.save_message(raw, record)["record_id"])
            store.flush()
            path = write_mail_review(store.records(), Path(directory) / "review.html")
            service = ReviewService(data_dir, page_path=path)
            try:
                result = subprocess.run(
                    [shutil.which("node"), str(Path(__file__).with_name("review_script_harness.cjs"))],
                    input=json.dumps({"script": REVIEW_SCRIPT, "pageUrl": service.page_url, "ids": ids}),
                    text=True, encoding="utf-8", capture_output=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(ArchiveStore(data_dir).excluded_record_ids(), {ids[0]})
                self.assertEqual(len(ArchiveStore(data_dir).records()), 2)
            finally:
                service.close()

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
            page_path = write_mail_review(store.reviewed_records(), Path(directory) / "mail_review.html")

            def rebuild() -> None:
                rebuilds.append(True)
                write_mail_review(ArchiveStore(data_dir).reviewed_records(), page_path)

            service = ReviewService(data_dir, rebuild, page_path=page_path)
            try:
                with urlopen(service.page_url, timeout=5) as response:
                    self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
                    self.assertIn(stored["record_id"], response.read().decode("utf-8"))
                with self.assertRaises(HTTPError) as denied:
                    urlopen(service.page_url.split("?", 1)[0], timeout=5)
                self.assertEqual(denied.exception.code, 403)

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

                origin = f"{urlsplit(service.url).scheme}://{urlsplit(service.url).netloc}"
                same_origin_request = Request(
                    service.url,
                    data=json.dumps({"action": "exclude", "record_ids": [stored["record_id"]]}).encode("utf-8"),
                    headers={"Origin": origin, "Content-Type": "application/json"},
                )
                with urlopen(same_origin_request, timeout=5) as response:
                    self.assertIn(stored["record_id"], json.load(response)["excluded_record_ids"])
                with urlopen(service.page_url, timeout=5) as response:
                    self.assertNotIn(stored["record_id"], response.read().decode("utf-8"))
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
        self.assertIn('id="save-review"', page)
        self.assertIn("action:'save'", page)
        self.assertIn("location.replace(destination.href)", page)
        self.assertIn("location.pathname==='/page'", page)


if __name__ == "__main__":
    unittest.main()
