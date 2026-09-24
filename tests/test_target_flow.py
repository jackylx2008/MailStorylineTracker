from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mail_storyline_tracker.modules.ai_client import AISettings, OpenAICompatibleClient
from mail_storyline_tracker.modules.html_report import write_target_mindmap
from mail_storyline_tracker.modules.target_config import TargetCriteria
from mail_storyline_tracker.flows.target_flow import build_target_storylines


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
            self.assertIn("折叠全部", content)
            self.assertIn("部分扫描结果", content)
            self.assertIn("测试限流", content)


if __name__ == "__main__":
    unittest.main()
