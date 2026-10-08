from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .mail_parser import attachment_payloads, public_record, safe_filename


class ArchiveStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.raw_dir = data_dir / "raw_mail"
        self.state_path = data_dir / "state" / "mail_sync_state.json"
        self.review_state_path = data_dir / "state" / "review_exclusions.json"
        self.records_path = data_dir / "records" / "mail_records.json"
        self._state = _read_json(self.state_path, {"version": 1, "items": {}})
        self._state.setdefault("fetch_limits", {})
        self._records = _read_json(self.records_path, {"version": 1, "records": {}})
        self._review_state = _read_json(self.review_state_path, {"version": 1, "excluded_record_ids": []})
        self._excluded_source_keys = self._review_excluded_source_keys()

    @staticmethod
    def state_key(account: str, mailbox: str, uidvalidity: str, uid: str) -> str:
        return "|".join((account.lower(), mailbox, uidvalidity, uid))

    def is_processed(self, key: str, filter_signature: str) -> bool:
        item = self._state["items"].get(key, {})
        return item.get("filter_signature") == filter_signature and item.get("status") in {"saved", "not_matched"}

    def is_review_excluded_source(self, key: str) -> bool:
        """在 FETCH 前跳过已审核排除的已知服务器来源，不受筛选签名变化影响。"""
        item = self._state["items"].get(key, {})
        return key in self._excluded_source_keys or item.get("record_id") in self.excluded_record_ids()

    def is_review_excluded_record(self, record_id: str) -> bool:
        return record_id in self.excluded_record_ids()

    def _review_excluded_source_keys(self) -> set[str]:
        keys = set(self._review_state.get("excluded_source_keys", []))
        for record_id in self.excluded_record_ids():
            record = self._records["records"].get(record_id, {})
            for source in record.get("sources", []):
                keys.add(self.state_key(
                    str(source.get("account", "")),
                    str(source.get("mailbox", "")),
                    str(source.get("uidvalidity", "")),
                    str(source.get("uid", "")),
                ))
        return keys

    def partial_record(self, key: str, filter_signature: str) -> dict[str, Any] | None:
        """返回已命中但尚未完整下载的记录，用于断点升级完整 EML 和附件。"""
        item = self._state["items"].get(key, {})
        if item.get("filter_signature") != filter_signature or item.get("status") != "saved":
            return None
        record = self._records["records"].get(item.get("record_id", ""))
        if not isinstance(record, dict) or not record.get("source_truncated"):
            return None
        return dict(record)

    def full_record_for_source(
        self,
        account: str,
        mailbox: str,
        uidvalidity: str,
        uid: str,
    ) -> dict[str, Any] | None:
        """查找其他下载队列已完整保存的同一服务器邮件，避免跨规则重复 FETCH。"""
        expected = {
            "account": account,
            "mailbox": mailbox,
            "uidvalidity": uidvalidity,
            "uid": uid,
        }
        for record in self._records["records"].values():
            if record.get("source_truncated"):
                continue
            path = Path(str(record.get("eml_path", "")))
            if path.suffix.lower() != ".eml" or not path.is_file():
                continue
            for source in record.get("sources", []):
                actual = {name: str(source.get(name, "")) for name in expected}
                if actual == expected:
                    return dict(record)
        return None

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
        if record["record_id"] in self.excluded_record_ids():
            self._excluded_source_keys = self._review_excluded_source_keys()
        return public

    def records(self) -> list[dict[str, Any]]:
        return sorted(self._records["records"].values(), key=lambda item: item.get("sent_at", ""))

    def excluded_record_ids(self) -> set[str]:
        return set(self._review_state.get("excluded_record_ids", []))

    def reviewed_records(self) -> list[dict[str, Any]]:
        excluded = self.excluded_record_ids()
        return [record for record in self.records() if str(record.get("record_id", "")) not in excluded]

    def update_review_exclusions(self, record_ids: set[str], *, excluded: bool) -> set[str]:
        return self.apply_review_decisions(record_ids if excluded else set(), set() if excluded else record_ids)

    def apply_review_decisions(self, exclude_ids: set[str], restore_ids: set[str]) -> set[str]:
        if exclude_ids & restore_ids:
            raise ValueError("同一邮件不能同时排除和恢复")
        unknown = (exclude_ids - self.excluded_record_ids() | restore_ids) - self._records["records"].keys()
        if unknown:
            raise KeyError(f"审核记录不存在：{len(unknown)} 条")
        current = self.excluded_record_ids()
        updated = (current | exclude_ids) - restore_ids
        if updated != current:
            self._review_state["excluded_record_ids"] = sorted(updated)
            _write_json_atomic(self.review_state_path, self._review_state)
            self._excluded_source_keys = self._review_excluded_source_keys()
        return updated

    def delete_excluded_content(self) -> int:
        """删除审核排除邮件的本地内容，持久保存去重标识。"""
        excluded = self.excluded_record_ids()
        keys = self._review_excluded_source_keys()
        self._review_state["excluded_source_keys"] = sorted(keys)
        _write_json_atomic(self.review_state_path, self._review_state)
        retained_paths = set()
        for record in self.reviewed_records():
            for value in [record.get("eml_path"), *[a.get("path") for a in record.get("attachments", [])]]:
                if value:
                    retained_paths.add(Path(value).resolve())
        paths = set()
        for rid in excluded:
            record = self._records["records"].get(rid, {})
            for value in [record.get("eml_path"), *[a.get("path") for a in record.get("attachments", [])]]:
                if value:
                    path = Path(value).resolve()
                    if not path.is_relative_to(self.raw_dir.resolve()):
                        raise ValueError("邮件文件不在本地归档目录内，停止删除")
                    if path not in retained_paths:
                        paths.add(path)
        for path in paths:
            path.unlink(missing_ok=True)
        count = 0
        for rid in excluded:
            if self._records["records"].pop(rid, None) is not None:
                count += 1
        self._excluded_source_keys = keys
        self.flush()
        return count

    def update_record_metadata(self, record_id: str, **values: Any) -> None:
        record = self._records["records"].get(record_id)
        if not isinstance(record, dict):
            raise KeyError(f"未找到本地邮件记录：{record_id}")
        record.update(values)

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
    for attempt in range(6):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 5:
                raise
            # CloudStation/OneDrive 可能短暂锁定目标文件，有限退避后再原子替换。
            time.sleep(0.25 * (2**attempt))
