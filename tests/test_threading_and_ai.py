from __future__ import annotations

import unittest

from mail_storyline_tracker.modules.ai_client import AISettings, OpenAICompatibleClient, parse_json_response
from mail_storyline_tracker.modules.threading import group_conversations, normalize_subject


def _record(record_id: str, message_id: str, subject: str, sent_at: str, references: list[str]) -> dict:
    return {
        "record_id": record_id,
        "message_id": message_id,
        "references": references,
        "in_reply_to": references[-1:] if references else [],
        "subject": subject,
        "sent_at": sent_at,
        "addresses": {"from": ["a@example.com"], "to": ["b@example.com"], "cc": []},
    }


class ThreadingAndAITests(unittest.TestCase):
    def test_reply_headers_group_messages(self) -> None:
        records = [
            _record("1", "<one@example.com>", "项目计划", "2026-09-01T08:00:00+08:00", []),
            _record("2", "<two@example.com>", "Re: 项目计划", "2026-09-02T08:00:00+08:00", ["<one@example.com>"]),
        ]
        groups = group_conversations(records)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["messages"]), 2)
        self.assertEqual(normalize_subject("回复： Re: 项目计划"), "项目计划")

    def test_json_code_fence_is_accepted(self) -> None:
        result = parse_json_response('```json\n{"matters": []}\n```')
        self.assertEqual(result, {"matters": []})

    def test_remote_ai_requires_explicit_opt_in(self) -> None:
        settings = AISettings("https://api.example.com/v1", "demo", "", False, 10, 10, 0, 100, 10)
        with self.assertRaisesRegex(RuntimeError, "远端 AI 默认关闭"):
            OpenAICompatibleClient(settings)


if __name__ == "__main__":
    unittest.main()
