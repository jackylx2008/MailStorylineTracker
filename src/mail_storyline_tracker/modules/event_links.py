"""Persist human decisions about evidence links without changing archived mail."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventLinkStore:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "state" / "event_link_decisions.json"

    def decisions(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict) or not isinstance(value.get("decisions"), dict):
            raise ValueError("事件链路审核状态格式不正确")
        return value["decisions"]

    @staticmethod
    def key(target: str, source_id: str, dest_id: str) -> str:
        return json.dumps([target, source_id, dest_id], ensure_ascii=False, separators=(",", ":"))

    def save(self, target: str, source_id: str, dest_id: str, decision: str) -> None:
        if decision not in {"approved", "rejected"}:
            raise ValueError("无效的链路审核决定")
        items = self.decisions()
        items[self.key(target, source_id, dest_id)] = {
            "decision": decision,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, "decisions": items}, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
