from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Mapping


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    user: str
    password: str
    support_email: str
    client_id: dict[str, str]
    folders: tuple[str, ...]
    since: str
    before: str
    max_messages_per_folder: int
    max_messages_per_run: int
    fetch_interval_seconds: float
    fetch_batch_size: int
    fetch_batch_pause_seconds: float
    volume_limit_cooldown_hours: int
    senders: tuple[str, ...]
    recipients: tuple[str, ...]
    keywords: tuple[str, ...]
    match_mode: str

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MailSettings":
        raw = config.get("mail", {})
        imap = raw.get("imap", {})
        client_id = {
            "name": "MailStorylineTracker",
            "version": "1.0",
            "vendor": "local-python",
            "support-email": str(imap.get("support_email", "support@example.invalid")),
        }
        client_id.update({str(key): str(value) for key, value in (imap.get("client_id") or {}).items()})
        settings = cls(
            host=str(imap.get("host", "imap.126.com")),
            port=int(imap.get("port", 993)),
            user=str(imap.get("user", "")).strip(),
            password=str(imap.get("password", "")),
            support_email=str(imap.get("support_email", "support@example.invalid")),
            client_id=client_id,
            folders=_strings(raw.get("folders")) or ("INBOX",),
            since=str(raw.get("since", "2024-01-01")),
            before=str(raw.get("before", "")),
            max_messages_per_folder=int(raw.get("max_messages_per_folder", 50)),
            max_messages_per_run=int(raw.get("max_messages_per_run", 50)),
            fetch_interval_seconds=float(raw.get("fetch_interval_seconds", 1.5)),
            fetch_batch_size=int(raw.get("fetch_batch_size", 10)),
            fetch_batch_pause_seconds=float(raw.get("fetch_batch_pause_seconds", 20)),
            volume_limit_cooldown_hours=int(raw.get("volume_limit_cooldown_hours", 24)),
            senders=_strings(raw.get("filters", {}).get("senders")),
            recipients=_strings(raw.get("filters", {}).get("recipients")),
            keywords=_strings(raw.get("filters", {}).get("keywords")),
            match_mode=str(raw.get("filters", {}).get("match_mode", "any")).lower(),
        )
        settings.validate_filters()
        return settings

    def with_overrides(self, values: Mapping[str, Any] | None) -> "MailSettings":
        if not values:
            return self
        changes: dict[str, Any] = {}
        for name in ("folders", "senders", "recipients", "keywords"):
            if name in values and values[name] is not None:
                changes[name] = _strings(values[name])
        for name in ("since", "before", "match_mode"):
            if name in values and values[name] is not None:
                changes[name] = str(values[name]).strip()
        if "max_messages_per_folder" in values and values["max_messages_per_folder"] is not None:
            changes["max_messages_per_folder"] = int(str(values["max_messages_per_folder"]).strip())
        result = replace(self, **changes)
        result.validate_filters()
        return result

    def validate_filters(self) -> None:
        if self.match_mode not in {"any", "all"}:
            raise ValueError("匹配方式必须是 any 或 all")
        if not self.folders:
            raise ValueError("至少选择一个邮件文件夹")
        if self.max_messages_per_folder <= 0:
            raise ValueError("每文件夹最多候选数必须是正整数")
        if self.max_messages_per_run <= 0:
            raise ValueError("单次运行最多处理数必须是正整数")
        if self.fetch_interval_seconds < 0 or self.fetch_batch_pause_seconds < 0:
            raise ValueError("FETCH 请求间隔和批次暂停不能为负数")
        if self.fetch_batch_size <= 0:
            raise ValueError("FETCH 批次大小必须是正整数")
        if self.volume_limit_cooldown_hours < 24:
            raise ValueError("依据 126 官方建议，流量限额冷却时间不能少于 24 小时")

    def validate_connection(self) -> None:
        if not self.host or not self.user or not self.password:
            raise ValueError("请先在 .env 中配置 MAIL_IMAP_USER 和 MAIL_IMAP_PASSWORD")
        if self.host.lower() != "imap.126.com":
            raise ValueError("第一阶段只支持 126.com，IMAP 主机必须是 imap.126.com")

    @property
    def filter_signature(self) -> str:
        payload = {
            "senders": sorted(value.lower() for value in self.senders),
            "recipients": sorted(value.lower() for value in self.recipients),
            "keywords": sorted(value.lower() for value in self.keywords),
            "mode": self.match_mode,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
