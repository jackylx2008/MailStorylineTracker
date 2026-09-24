from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TargetCriteria:
    emails: tuple[str, ...]
    keywords: tuple[str, ...]
    files: tuple[str, ...]

    @classmethod
    def load(cls, project_root: Path) -> "TargetCriteria":
        criteria = cls(
            emails=_read_lines(project_root / "target_email.env"),
            keywords=_read_lines(project_root / "target_keyword.env"),
            files=_read_lines(project_root / "target_file.env"),
        )
        criteria.validate()
        return criteria

    @classmethod
    def from_values(
        cls,
        emails: str | tuple[str, ...] | list[str],
        keywords: str | tuple[str, ...] | list[str],
        files: str | tuple[str, ...] | list[str],
    ) -> "TargetCriteria":
        """从 GUI 多行文本或序列构建当前运行使用的目标配置。"""
        criteria = cls(
            emails=_normalize_values(emails),
            keywords=_normalize_values(keywords),
            files=_normalize_values(files),
        )
        criteria.validate()
        return criteria

    def validate(self) -> None:
        if not self.emails and not self.keywords and not self.files:
            raise ValueError("target_email.env、target_keyword.env 和 target_file.env 均为空")
        if not self.files:
            raise ValueError("target_file.env 至少需要一个独立事项")

    @property
    def signature(self) -> str:
        payload = {
            "emails": sorted(value.lower() for value in self.emails),
            "keywords": sorted(value.lower() for value in self.keywords),
            "files": sorted(value.lower() for value in self.files),
            "mode": "email_or_keyword_or_attachment_ai",
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _read_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        raise FileNotFoundError(f"缺少本地目标配置：{path.name}")
    return _normalize_values(path.read_text(encoding="utf-8-sig"))


def _normalize_values(value: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    raw_values = value.splitlines() if isinstance(value, str) else value
    values: list[str] = []
    for raw in raw_values:
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value not in values:
            values.append(value)
    return tuple(values)
