from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mail_storyline_tracker.modules.imap_client import (
    _is_fetch_volume_limit,
    _or_search_keys,
    decode_modified_utf7,
    encode_modified_utf7,
    is_imap_connection_error,
)
from mail_storyline_tracker.modules.storage import ArchiveStore


class StorageAndImapTests(unittest.TestCase):
    def test_modified_utf7_round_trip(self) -> None:
        for value in ("INBOX", "已发送", "项目&A"):
            self.assertEqual(decode_modified_utf7(encode_modified_utf7(value)), value)

    def test_fetch_volume_limit_is_detected_in_nested_response(self) -> None:
        self.assertTrue(_is_fetch_volume_limit([b"FETCH Fetch volume limit exceed"]))
        self.assertFalse(_is_fetch_volume_limit([b"ordinary fetch error"]))

    def test_connection_errors_are_classified_for_safe_stop(self) -> None:
        self.assertTrue(is_imap_connection_error(ConnectionResetError("reset")))
        self.assertFalse(is_imap_connection_error(ValueError("bad input")))

    def test_multiple_terms_form_one_nested_or_search(self) -> None:
        self.assertEqual(
            _or_search_keys("TEXT", ("声学", "减震", "噪声")),
            ["OR", "TEXT", "声学".encode("utf-8").join((b'"', b'"')), "OR", "TEXT", "减震".encode("utf-8").join((b'"', b'"')), "TEXT", "噪声".encode("utf-8").join((b'"', b'"'))],
        )

    def test_incremental_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArchiveStore(Path(directory))
            key = store.state_key("demo@126.com", "INBOX", "7", "99")
            store.mark(key, message_id="<demo@example.com>", content_sha256="abc", status="not_matched", filter_signature="filter-a")
            store.flush()
            loaded = ArchiveStore(Path(directory))
            self.assertTrue(loaded.is_processed(key, "filter-a"))
            self.assertFalse(loaded.is_processed(key, "filter-b"))

    def test_fetch_limit_cooldown_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArchiveStore(Path(directory))
            blocked_until = store.mark_fetch_limited("demo@126.com", 24)
            store.flush()
            loaded = ArchiveStore(Path(directory))
            self.assertEqual(loaded.fetch_blocked_until("demo@126.com"), blocked_until)


if __name__ == "__main__":
    unittest.main()
