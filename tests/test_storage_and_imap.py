from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mail_storyline_tracker.modules.imap_client import decode_modified_utf7, encode_modified_utf7
from mail_storyline_tracker.modules.storage import ArchiveStore


class StorageAndImapTests(unittest.TestCase):
    def test_modified_utf7_round_trip(self) -> None:
        for value in ("INBOX", "已发送", "项目&A"):
            self.assertEqual(decode_modified_utf7(encode_modified_utf7(value)), value)

    def test_incremental_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArchiveStore(Path(directory))
            key = store.state_key("demo@126.com", "INBOX", "7", "99")
            store.mark(key, message_id="<demo@example.com>", content_sha256="abc", status="not_matched", filter_signature="filter-a")
            store.flush()
            loaded = ArchiveStore(Path(directory))
            self.assertTrue(loaded.is_processed(key, "filter-a"))
            self.assertFalse(loaded.is_processed(key, "filter-b"))


if __name__ == "__main__":
    unittest.main()
