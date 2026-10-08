from __future__ import annotations

import unittest
from unittest.mock import patch
import json
import io
import urllib.error

from mail_storyline_tracker.modules.ai_client import AISettings, OpenAICompatibleClient, build_prompt, parse_json_response
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

    def test_summary_batches_include_every_message_and_report_progress(self) -> None:
        settings = AISettings("http://127.0.0.1:8080/v1", "demo", "", False, 10, 2048, 0, 60000, 600)
        client = OpenAICompatibleClient(settings)
        client.resolved_model = "demo"
        records = [
            {"record_id": str(number), "body_text": "测试正文" * 45, "attachments": []}
            for number in range(11)
        ]
        conversations = [{"conversation_id": "one", "messages": records}]
        sent_ids = []
        outputs = []

        def fake_request(url, payload=None):
            self.assertTrue(url.endswith("/chat/completions"))
            self.assertLess(payload["max_tokens"], 2048)
            prompt = payload["messages"][1]["content"]
            sent_ids.extend(record["record_id"] for record in records if f'"record_id": "{record["record_id"]}"' in prompt)
            outputs.append(prompt)
            return {"choices": [{"message": {"content": '{"matters": []}'}}]}

        progress = []
        with patch.object(client, "_context_size", return_value=4096), patch.object(
            client, "_prompt_tokens", side_effect=lambda prompt: len(prompt) // 2
        ), patch.object(client, "_request", side_effect=fake_request):
            result = client.summarize(conversations, lambda done, total: progress.append((done, total)))
        self.assertGreater(result["batch_count"], 1)
        self.assertEqual(sorted(sent_ids, key=int), [str(number) for number in range(11)])
        self.assertEqual(len(outputs), result["batch_count"])
        self.assertEqual(progress[-1], (result["batch_count"], result["batch_count"]))

    def test_prompt_does_not_silently_drop_messages_at_character_limit(self) -> None:
        settings = AISettings("http://127.0.0.1:8080/v1", "demo", "", False, 10, 1024, 0, 100, 600)
        prompt = build_prompt([{"conversation_id": "one", "messages": [
            {"record_id": "first", "body_text": "正文", "attachments": []},
            {"record_id": "second", "body_text": "正文", "attachments": []},
        ]}], settings)
        self.assertIn("first", prompt)
        self.assertIn("second", prompt)

    def test_focused_prompt_excludes_unrelated_matters(self) -> None:
        settings = AISettings("http://127.0.0.1:8080/v1", "demo", "", False, 10, 1024, 0, 6000, 600)
        prompt = build_prompt([{"conversation_id": "one", "messages": []}], settings, "风冷热泵")
        self.assertIn("最终文件关键词 \"风冷热泵\"", prompt)
        self.assertIn("不得为无关事项生成条目", prompt)

    def test_http_400_exposes_server_reason(self) -> None:
        settings = AISettings("http://127.0.0.1:8080/v1", "demo", "", False, 10, 1024, 0, 6000, 600)
        client = OpenAICompatibleClient(settings)
        body = io.BytesIO(json.dumps({"error": {"message": "request exceeds available context size"}}).encode())
        error = urllib.error.HTTPError("http://127.0.0.1:8080/v1/chat/completions", 400, "Bad Request", {}, body)
        with patch("mail_storyline_tracker.modules.ai_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "exceeds available context size"):
                client._request(settings.base_url + "/chat/completions", {"messages": []})


if __name__ == "__main__":
    unittest.main()
