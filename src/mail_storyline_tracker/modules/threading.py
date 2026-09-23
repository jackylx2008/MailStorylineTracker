from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any


SUBJECT_PREFIX = re.compile(r"^(?:(?:re|fw|fwd|回复|转发)\s*[:：]\s*)+", re.IGNORECASE)
BRACKET_TAG = re.compile(r"^\s*[\[【][^\]】]{1,30}[\]】]\s*")


def group_conversations(records: list[dict[str, Any]], proximity_days: int = 90) -> list[dict[str, Any]]:
    if not records:
        return []
    parent = list(range(len(records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    message_ids: dict[str, int] = {}
    for index, record in enumerate(records):
        message_id = str(record.get("message_id", "")).lower()
        if message_id:
            message_ids[message_id] = index
    for index, record in enumerate(records):
        for reference in [*record.get("references", []), *record.get("in_reply_to", [])]:
            target = message_ids.get(str(reference).lower())
            if target is not None:
                union(index, target)

    by_subject: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        subject = normalize_subject(str(record.get("subject", "")))
        if subject:
            by_subject.setdefault(subject, []).append(index)
    window = timedelta(days=proximity_days)
    for indexes in by_subject.values():
        indexes.sort(key=lambda item: _date(records[item]))
        for left, right in zip(indexes, indexes[1:]):
            if _participants(records[left]) & _participants(records[right]) and _date(records[right]) - _date(records[left]) <= window:
                union(left, right)

    groups: dict[int, list[dict[str, Any]]] = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)
    result = []
    for number, messages in enumerate(groups.values(), start=1):
        messages.sort(key=_date)
        result.append(
            {
                "conversation_id": f"conversation-{number:04d}",
                "normalized_subject": normalize_subject(str(messages[0].get("subject", ""))) or "无主题",
                "participants": sorted(set().union(*(_participants(item) for item in messages))),
                "first_at": messages[0].get("sent_at", ""),
                "last_at": messages[-1].get("sent_at", ""),
                "messages": messages,
            }
        )
    return sorted(result, key=lambda item: item["last_at"], reverse=True)


def normalize_subject(value: str) -> str:
    current = value.strip()
    previous = None
    while previous != current:
        previous = current
        current = SUBJECT_PREFIX.sub("", current).strip()
        current = BRACKET_TAG.sub("", current).strip()
    return re.sub(r"\s+", " ", current).lower()


def _participants(record: dict[str, Any]) -> set[str]:
    addresses = record.get("addresses", {})
    return {str(value).lower() for key in ("from", "to", "cc") for value in addresses.get(key, [])}


def _date(record: dict[str, Any]) -> datetime:
    try:
        return datetime.fromisoformat(str(record.get("sent_at", ""))).replace(tzinfo=None)
    except ValueError:
        return datetime.min
