from __future__ import annotations

import unittest
from email.message import EmailMessage

from mail_storyline_tracker.modules.mail_parser import matches_filters, parse_message


class MailParserTests(unittest.TestCase):
    def setUp(self) -> None:
        message = EmailMessage()
        message["From"] = "Alice <alice@example.com>"
        message["To"] = "team@example.com"
        message["Cc"] = "owner@example.net"
        message["Subject"] = "Re: 示例项目验收"
        message["Date"] = "Wed, 23 Sep 2026 09:00:00 +0800"
        message["Message-ID"] = "<second@example.com>"
        message["In-Reply-To"] = "<first@example.com>"
        message["References"] = "<first@example.com>"
        message.set_content("请在周五前完成验收并回复。")
        message.add_attachment(b"demo", maintype="application", subtype="pdf", filename="验收单.pdf")
        self.record = parse_message(message.as_bytes(), account="demo@126.com", mailbox="INBOX", uidvalidity="9", uid="10")

    def test_parse_headers_body_and_attachment(self) -> None:
        self.assertEqual(self.record["addresses"]["from"], ["alice@example.com"])
        self.assertEqual(self.record["in_reply_to"], ["<first@example.com>"])
        self.assertIn("周五前", self.record["body_text"])
        self.assertEqual(self.record["attachments"][0]["filename"], "验收单.pdf")

    def test_any_and_all_filter_groups(self) -> None:
        matched, reasons = matches_filters(self.record, ("nobody@example.com",), ("team@example.com",), ("不存在",), "any")
        self.assertTrue(matched)
        self.assertEqual(reasons, ["收件人/Cc"])
        matched, _ = matches_filters(self.record, ("alice@example.com",), ("team@example.com",), ("验收",), "all")
        self.assertTrue(matched)
        matched, _ = matches_filters(self.record, ("alice@example.com",), ("wrong@example.com",), ("验收",), "all")
        self.assertFalse(matched)


if __name__ == "__main__":
    unittest.main()
