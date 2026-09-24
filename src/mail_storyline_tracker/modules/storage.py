from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .mail_parser import attachment_payloads, public_record, safe_filename


class ArchiveStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.raw_dir = data_dir / "raw_mail"
        self.state_path = data_dir / "state" / "mail_sync_state.json"
        self.records_path = data_dir / "records" / "mail_records.json"
        self._state = _read_json(self.state_path, {"version": 1, "items": {}})
        self._state.setdefault("fetch_limits", {})
        self._records = _read_json(self.records_path, {"version": 1, "records": {}})

    @staticmethod
    def state_key(account: str, mailbox: str, uidvalidity: str, uid: str) -> str:
        return "|".join((account.lower(), mailbox, uidvalidity, uid))

    def is_processed(self, key: str, filter_signature: str) -> bool:
        item = self._state["items"].get(key, {})
        return item.get("filter_signature") == filter_signature and item.get("status") in {"saved", "not_matched"}

    def mark(self, key: str, *, message_id: str, content_sha256: str, status: str, filter_signature: str, record_id: str = "") -> None:
        self._state["items"][key] = {
            "message_id": message_id,
            "content_sha256": content_sha256,
            "status": status,
            "filter_signature": filter_signature,
            "record_id": record_id,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def fetch_blocked_until(self, account: str) -> str:
        item = self._state["fetch_limits"].get(account.lower(), {})
        value = str(item.get("blocked_until", ""))
        if not value:
            return ""
        try:
            blocked_until = datetime.fromisoformat(value)
        except ValueError:
            return ""
        return value if blocked_until > datetime.now(timezone.utc) else ""

    def mark_fetch_limited(self, account: str, cooldown_hours: int) -> str:
        now = datetime.now(timezone.utc)
        blocked_until = now + timedelta(hours=cooldown_hours)
        self._state["fetch_limits"][account.lower()] = {
            "detected_at": now.isoformat(),
            "blocked_until": blocked_until.isoformat(),
            "reason": "126 IMAP FETCH volume limit exceed",
        }
        return blocked_until.isoformat()

    def save_message(self, raw_bytes: bytes, record: dict[str, Any]) -> dict[str, Any]:
        folder = safe_filename(record["mailbox"])
        stem = f"{record['uid']}_{record['content_sha256'][:12]}"
        suffix = ".eml.partial" if record.get("source_truncated") else ".eml"
        eml_path = self.raw_dir / folder / "eml" / f"{stem}{suffix}"
        eml_path.parent.mkdir(parents=True, exist_ok=True)
        if not eml_path.exists():
            eml_path.write_bytes(raw_bytes)
        record["eml_path"] = str(eml_path)
        target_dir = self.raw_dir / folder / "attachments" / stem
        public = public_record(record)
        payload_items = [] if record.get("source_truncated") else attachment_payloads(record)
        for attachment, (filename, payload) in zip(public["attachments"], payload_items):
            if not payload:
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / safe_filename(filename)
            if not path.exists():
                path.write_bytes(payload)
            attachment["path"] = str(path)
        existing = self._records["records"].get(record["record_id"])
        if existing:
            sources = existing.get("sources", [])
            source = {"account": record["account"], "mailbox": record["mailbox"], "uidvalidity": record["uidvalidity"], "uid": record["uid"]}
            if source not in sources:
                sources.append(source)
            public["sources"] = sources
            self._records["records"][record["record_id"]] = public
        else:
            public["sources"] = [{"account": record["account"], "mailbox": record["mailbox"], "uidvalidity": record["uidvalidity"], "uid": record["uid"]}]
            self._records["records"][record["record_id"]] = public
        return public

    def records(self) -> list[dict[str, Any]]:
        return sorted(self._records["records"].values(), key=lambda item: item.get("sent_at", ""))

    def flush(self) -> None:
        _write_json_atomic(self.state_path, self._state)
        _write_json_atomic(self.records_path, self._records)
        jsonl = self.records_path.with_suffix(".jsonl")
        jsonl.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in self.records())
        _write_text_atomic(jsonl, text)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else default
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, value: Any) -> None:
    _write_text_atomic(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)
