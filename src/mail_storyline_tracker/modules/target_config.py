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
    values: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value not in values:
            values.append(value)
    return tuple(values)
