from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import CancelledError
from email.message import EmailMessage
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from mail_storyline_tracker.config import AppContext
from mail_storyline_tracker.modules.ai_client import AISettings, OpenAICompatibleClient
from mail_storyline_tracker.modules.html_report import write_target_mindmap
from mail_storyline_tracker.modules.mail_parser import parse_message
from mail_storyline_tracker.modules.storage import ArchiveStore
from mail_storyline_tracker.modules.target_config import TargetCriteria
from mail_storyline_tracker.flows.target_flow import _process_batch, build_target_storylines, generate_target_report, scan_targets
from mail_storyline_tracker.modules.imap_client import MailboxInfo
from mail_storyline_tracker.modules.event_links import EventLinkStore
from mail_storyline_tracker.modules.review_service import ReviewService


def _record(record_id: str, message_id: str, subject: str, sent_at: str, *, target: str = "", reference: str = "") -> dict:
    matches = [{"filename": "示例审核意见V2.pdf", "target": target, "confidence": 0.93, "reason": "语义一致"}] if target else []
    return {
        "record_id": record_id,
        "message_id": message_id,
        "references": [reference] if reference else [],
        "in_reply_to": [reference] if reference else [],
        "subject": subject,
        "sent_at": sent_at,
        "from": "Alice <alice@example.com>",
        "to": "team@example.com",
        "cc": "",
        "addresses": {"from": ["alice@example.com"], "to": ["team@example.com"], "cc": []},
        "body_text": "请审核并回复。",
        "attachments": [{"filename": "示例审核意见V2.pdf"}] if target else [],
        "target_matches": matches,
        "matched_by": ["目标附件名（本地 AI 模糊匹配）"] if target else ["目标联系人"],
        "mailbox": "INBOX",
        "uid": record_id,
    }


class TargetFlowTests(unittest.TestCase):
    def test_target_scan_user_cancel_does_not_fetch_or_log_error(self) -> None:
        class FakeClient:
            def __init__(self, settings) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def list_mailboxes(self):
                return [MailboxInfo("INBOX", (), "/")]

            def select_mailbox(self, mailbox):
                return 1, "7"

            def search_uids(self, since, before, maximum):
                return ["8"]

            def fetch_message_preview(self, uid, max_bytes):
                raise AssertionError("取消后不应预览 FETCH")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {"imap": {"user": "demo@126.com", "password": "secret"}},
            })

            def cancel(_label: str, _done: int, _total: int) -> None:
                raise CancelledError("任务已取消")

            with patch("mail_storyline_tracker.flows.target_flow.Imap126Client", FakeClient), patch(
                "mail_storyline_tracker.flows.target_flow.OpenAICompatibleClient"
            ), patch("mail_storyline_tracker.flows.target_flow.logger.exception") as log_exception:
                result = scan_targets(ctx, progress=cancel, criteria=TargetCriteria(("alice@example.com",), (), ()))
            self.assertTrue(result["summary"]["cancelled"])
            self.assertTrue(result["summary"]["incomplete"])
            self.assertEqual(result["summary"]["errors"], 0)
            log_exception.assert_not_called()

    def test_target_scan_skips_review_excluded_source_before_fetch(self) -> None:
        message = EmailMessage()
        message["From"] = "alice@example.com"
        message["To"] = "team@example.com"
        message["Message-ID"] = "<excluded-target@example.com>"
        message.set_content("请审核。")
        raw = message.as_bytes()

        class FakeClient:
            def __init__(self, settings) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def list_mailboxes(self):
                return [MailboxInfo("INBOX", (), "/")]

            def select_mailbox(self, mailbox):
                return 1, "7"

            def search_uids(self, since, before, maximum):
                return ["8"]

            def fetch_message_preview(self, uid, max_bytes):
                raise AssertionError("已排除邮件不应预览 FETCH")

            def fetch_message(self, uid):
                raise AssertionError("已排除邮件不应完整 FETCH")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {
                "app": {"data_dir": "data", "output_dir": "output"},
                "mail": {"imap": {"user": "demo@126.com", "password": "secret"}},
            })
            store = ArchiveStore(ctx.data_dir)
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="7", uid="8")
            stored = store.save_message(raw, record)
            store.flush()
            store.update_review_exclusions({stored["record_id"]}, excluded=True)
            with patch("mail_storyline_tracker.flows.target_flow.Imap126Client", FakeClient), patch(
                "mail_storyline_tracker.flows.target_flow.OpenAICompatibleClient"
            ) as ai_client:
                result = scan_targets(ctx, criteria=TargetCriteria(("alice@example.com",), (), ()))
            ai_client.return_value.check.assert_called_once()
            self.assertEqual(result["summary"]["review_excluded_skipped"], 1)

    def test_excluded_mail_does_not_appear_in_regenerated_target_chain(self) -> None:
        message = EmailMessage()
        message["From"] = "alice@example.com"
        message["To"] = "team@example.com"
        message["Subject"] = "示例审核资料"
        message["Message-ID"] = "<target-review@example.com>"
        message.set_content("请审核附件。")
        message.add_attachment(b"example", maintype="application", subtype="pdf", filename="review.pdf")
        raw = message.as_bytes()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx = AppContext(root, {"app": {"data_dir": "data", "output_dir": "output"}})
            store = ArchiveStore(ctx.data_dir)
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="1", uid="8")
            criteria = TargetCriteria((), (), ("review",))
            stored = store.save_message(raw, record)
            store.flush()
            generate_target_report(ctx, criteria)
            before = json.loads((ctx.output_dir / "target_storylines.json").read_text(encoding="utf-8"))
            self.assertEqual(len(before["targets"][0]["events"]), 1)
            store.update_review_exclusions({stored["record_id"]}, excluded=True)
            generate_target_report(ctx, criteria)
            after = json.loads((ctx.output_dir / "target_storylines.json").read_text(encoding="utf-8"))
            self.assertEqual(after["targets"][0]["events"], [])

    def test_manual_filename_keyword_starts_backward_trace_without_ai_match(self) -> None:
        record = _record("file", "<file@example.com>", "最终文件", "2026-09-01T08:00:00+08:00")
        record["attachments"] = [{"filename": "项目_设备品牌推荐表-V2.pdf"}]
        earlier = _record("earlier", "<earlier@example.com>", "Re: 最终文件", "2026-08-31T08:00:00+08:00")
        earlier["references"] = ["<file@example.com>"]
        criteria = TargetCriteria((), (), ("设备品牌推荐表",))
        result = build_target_storylines([record, earlier], criteria, filename_only=True)
        topic = result["targets"][0]
        self.assertEqual(topic["seed_record_ids"], ["file"])
        self.assertIn("项目_设备品牌推荐表-V2.pdf", topic["attachment_names"])
        self.assertEqual(topic["anchor_record_id"], "file")
        self.assertEqual(len(topic["events"]), 2)
        ai_only = _record("ai", "<ai@example.com>", "无关主题", "2026-09-02T08:00:00+08:00", target="设备品牌推荐表")
        ai_only["attachments"] = [{"filename": "unrelated.pdf"}]
        self.assertEqual(build_target_storylines([ai_only], criteria, filename_only=True)["targets"][0]["events"], [])

    def test_matched_target_downloads_full_eml_and_attachment_once(self) -> None:
        message = EmailMessage()
        message["From"] = "Alice <alice@example.com>"
        message["To"] = "team@example.com"
        message["Subject"] = "审核资料"
        message["Message-ID"] = "<full-target@example.com>"
        message.set_content("请审核附件。")
        message.add_attachment(b"complete payload", maintype="application", subtype="pdf", filename="review.pdf")
        raw = message.as_bytes()

        class FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def fetch_message(self, uid: str) -> bytes:
                self.calls += 1
                return raw

        class FakeAI:
            def match_attachment_names(self, filenames, targets):
                return {}

        with tempfile.TemporaryDirectory() as directory:
            store = ArchiveStore(Path(directory))
            criteria = TargetCriteria(("alice@example.com",), (), ("review",))
            record = parse_message(raw, account="demo@126.com", mailbox="INBOX", uidvalidity="1", uid="8")
            record["source_truncated"] = True
            key = store.state_key("demo@126.com", "INBOX", "1", "8")
            client = FakeClient()
            saved = _process_batch([(key, raw, record)], store, criteria, FakeAI(), client)
            stored = store.records()[0]

            self.assertEqual(saved, 1)
            self.assertEqual(client.calls, 1)
            self.assertFalse(stored.get("source_truncated", False))
            self.assertTrue(Path(stored["eml_path"]).exists())
            self.assertTrue(Path(stored["attachments"][0]["path"]).exists())
            self.assertIsNone(store.partial_record(key, criteria.signature))

    def test_target_files_are_loaded_as_independent_items(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target_email.env").write_text("a@example.com\n", encoding="utf-8")
            (root / "target_keyword.env").write_text("审核\n", encoding="utf-8")
            (root / "target_file.env").write_text("事项甲\n事项乙\n", encoding="utf-8")
            criteria = TargetCriteria.load(root)
            self.assertEqual(criteria.files, ("事项甲", "事项乙"))

    def test_gui_multiline_values_ignore_comments_and_duplicates(self) -> None:
        criteria = TargetCriteria.from_values(
            "a@example.com\n# comment\na@example.com\n",
            "审核\n验收\n",
            "事项甲\n事项乙\n事项甲\n",
        )
        self.assertEqual(criteria.emails, ("a@example.com",))
        self.assertEqual(criteria.keywords, ("审核", "验收"))
        self.assertEqual(criteria.files, ("事项甲", "事项乙"))

    def test_ai_filename_matcher_keeps_only_known_targets(self) -> None:
        settings = AISettings("http://127.0.0.1:8080/v1", "local-model", "", False, 10, 100, 0, 1000, 100)
        client = OpenAICompatibleClient(settings)
        response = {
            "choices": [{"message": {"content": '{"matches":[{"filename":"示例审核V2.pdf","target":"示例审核意见","confidence":0.91,"reason":"版本名称相近"},{"filename":"示例审核V2.pdf","target":"不存在事项","confidence":1,"reason":"错误目标"}]}'}}]
        }
        with patch.object(client, "check", return_value={"resolved_model": "demo"}), patch.object(client, "_request", return_value=response):
            result = client.match_attachment_names(["示例审核V2.pdf"], ["示例审核意见"])
        self.assertEqual(result["示例审核V2.pdf"][0]["target"], "示例审核意见")
        self.assertEqual(len(result["示例审核V2.pdf"]), 1)

    def test_seed_attachment_includes_reply_chain_and_html(self) -> None:
        target = "示例审核意见"
        records = [
            _record("1", "<one@example.com>", "示例审核意见", "2026-09-01T08:00:00+08:00", target=target),
            _record("2", "<two@example.com>", "Re: 示例审核意见", "2026-09-02T08:00:00+08:00", reference="<one@example.com>"),
        ]
        result = build_target_storylines(records, TargetCriteria(("alice@example.com",), ("审核",), (target, "另一个事项")))
        self.assertEqual(len(result["targets"]), 2)
        self.assertEqual(len(result["targets"][0]["events"]), 2)
        self.assertEqual(len(result["targets"][1]["events"]), 0)
        first, second = result["targets"][0]["events"]
        self.assertEqual(second["parent_record_id"], first["record_id"])
        self.assertEqual(second["link_type"], "reply")
        self.assertEqual(second["body_text"], "请审核并回复。")
        topic = result["targets"][0]
        self.assertEqual(topic["anchor_record_id"], first["record_id"])
        self.assertEqual(topic["result_record_id"], first["record_id"])
        self.assertEqual(topic["edges"][0]["evidence"], "reply")
        self.assertEqual(topic["edges"][0]["decision"], "pending")
        self.assertEqual(topic["confirmed_record_ids"], [first["record_id"]])
        with tempfile.TemporaryDirectory() as directory:
            path = write_target_mindmap(
                {
                    **result,
                    "generated_at": "2026-09-24",
                    "incomplete": True,
                    "stop_reason": "测试限流",
                },
                Path(directory) / "map.html",
            )
            content = path.read_text(encoding="utf-8")
            self.assertIn("附件往来沟通链路", content)
            self.assertIn("示例审核意见", content)
            self.assertIn("独立事项", content)
            self.assertIn("部分扫描结果", content)
            self.assertIn("测试限流", content)
            self.assertIn("graph-scroll", content)
            self.assertIn("showModal()", content)
            self.assertIn("邮件正文", content)

    def test_confirmation_endpoint_and_human_link_decision(self) -> None:
        target = "示例审核意见"
        sent = _record("sent", "<sent@example.com>", target, "2026-09-01T08:00:00+08:00", target=target)
        reply = _record("reply", "<reply@example.com>", "Re: " + target, "2026-09-02T08:00:00+08:00", reference="<sent@example.com>")
        reply["body_text"] = "确认收到并同意。"
        reply["from"] = "Team <team@example.com>"
        unrelated = _record("other", "<other@example.com>", "完全无关", "2026-09-03T08:00:00+08:00")
        criteria = TargetCriteria((), (), (target,))
        report = build_target_storylines([sent, reply, unrelated], criteria)
        item = report["targets"][0]
        self.assertEqual(item["result_record_id"], "reply")
        self.assertTrue(item["result_is_confirmation"])
        self.assertEqual(item["confirmed_record_ids"], ["reply"])
        self.assertNotIn("other", [event["record_id"] for event in item["events"]])
        with tempfile.TemporaryDirectory() as directory:
            store = EventLinkStore(Path(directory))
            store.save(target, "sent", "reply", "approved")
            approved = build_target_storylines([sent, reply, unrelated], criteria, store.decisions())["targets"][0]
            self.assertEqual(approved["confirmed_record_ids"], ["reply", "sent"])
            store.save(target, "sent", "reply", "rejected")
            rejected = build_target_storylines([sent, reply, unrelated], criteria, store.decisions())["targets"][0]
            self.assertEqual(rejected["confirmed_record_ids"], ["reply"])

        reply["body_text"] = "请确认收到后回复。"
        pending = build_target_storylines([sent, reply], criteria)["targets"][0]
        self.assertEqual(pending["result_record_id"], "sent")

    def test_event_link_service_validates_and_persists_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "target_storylines.html"
            path.write_text("<html></html>", encoding="utf-8")
            path.with_suffix(".json").write_text(json.dumps({"targets": [{"target": "事项", "edges": [
                {"from_record_id": "one", "to_record_id": "two"}
            ]}]}, ensure_ascii=False), encoding="utf-8")
            rebuilt = []
            service = ReviewService(root / "data", lambda: rebuilt.append(True), storyline_path=path)
            try:
                with urlopen(service.storyline_url, timeout=5) as response:
                    self.assertIn(b"html", response.read())

                def post(source: str) -> int:
                    request = Request(service.event_link_url, data=json.dumps({
                        "target": "事项", "from_record_id": source,
                        "to_record_id": "two", "decision": "approved",
                    }).encode(), headers={"Content-Type": "application/json"})
                    with urlopen(request, timeout=5) as response:
                        return response.status
                with self.assertRaises(HTTPError) as invalid:
                    post("unknown")
                self.assertEqual(invalid.exception.code, 400)
                self.assertEqual(post("one"), 200)
                self.assertEqual(len(rebuilt), 1)
                self.assertEqual(EventLinkStore(root / "data").decisions()[EventLinkStore.key("事项", "one", "two")]["decision"], "approved")
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
