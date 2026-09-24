from __future__ import annotations

import base64
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from .mail_settings import MailSettings


logger = logging.getLogger(__name__)


class FetchVolumeLimitError(RuntimeError):
    """126 拒绝继续 FETCH，通常表示账号触发阶段性下载流量限制。"""


@dataclass(frozen=True)
class MailboxInfo:
    name: str
    flags: tuple[str, ...]
    delimiter: str


class Imap126Client:
    """复用已验证的 126.com 登录、ID 和只读邮箱访问流程。"""

    def __init__(self, settings: MailSettings) -> None:
        self.settings = settings
        self._client: imaplib.IMAP4_SSL | None = None
        self.selected_mailbox = ""
        self.uidvalidity = ""

    def __enter__(self) -> "Imap126Client":
        self.settings.validate_connection()
        logger.info("连接 126 IMAP：host=%s port=%s user=%s", self.settings.host, self.settings.port, _mask_email(self.settings.user))
        self._client = imaplib.IMAP4_SSL(self.settings.host, self.settings.port, timeout=90)
        self._client.login(self.settings.user, self.settings.password)
        self._send_client_id()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        client = self._client
        if client is None:
            return
        if self.selected_mailbox:
            try:
                client.close()
            except (imaplib.IMAP4.error, OSError):
                pass
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
        finally:
            self._client = None

    def list_mailboxes(self) -> list[MailboxInfo]:
        status, payload = self._require().list()
        if status != "OK":
            raise RuntimeError(f"读取邮箱文件夹失败：{status}")
        result: list[MailboxInfo] = []
        pattern = re.compile(rb'^\((?P<flags>[^)]*)\)\s+"?(?P<delimiter>[^" ]*)"?\s+(?P<name>.+)$')
        for raw in payload or []:
            if not isinstance(raw, bytes):
                continue
            match = pattern.match(raw)
            if not match:
                continue
            raw_name = match.group("name").strip().strip(b'"')
            result.append(
                MailboxInfo(
                    name=decode_modified_utf7(raw_name.decode("ascii", errors="replace")),
                    flags=tuple(item.decode("ascii", errors="replace") for item in match.group("flags").split()),
                    delimiter=match.group("delimiter").decode("ascii", errors="replace"),
                )
            )
        return result

    def select_mailbox(self, mailbox: str) -> tuple[int, str]:
        encoded = encode_modified_utf7(mailbox)
        status, payload = self._require().select(f'"{encoded}"', readonly=True)
        if status != "OK":
            raise RuntimeError(f"无法只读打开邮箱文件夹 {mailbox!r}：{payload!r}")
        self.selected_mailbox = mailbox
        uid_payload = self._require().response("UIDVALIDITY")[1]
        self.uidvalidity = _first_ascii(uid_payload) or "unknown"
        return int(_first_ascii(payload) or "0"), self.uidvalidity

    def search_uids(self, since: str, before: str, maximum: int) -> list[str]:
        uids = _newest_first(self._search(_date_criteria(since, before)))
        return uids[:maximum] if maximum > 0 else uids

    def search_filtered_uids(
        self,
        since: str,
        before: str,
        maximum: int,
        senders: tuple[str, ...],
        recipients: tuple[str, ...],
        keywords: tuple[str, ...],
        match_mode: str,
    ) -> tuple[list[str], dict[str, list[str]]]:
        """用轻量服务器条件缩小范围；正文匹配由调用方读取小预览完成。"""
        base = _date_criteria(since, before)
        date_uids = set(self._search(base))
        groups: list[tuple[str, set[str]]] = []
        if senders:
            groups.append(("发件人", set(self._search([*base, *_or_search_keys("FROM", senders)], charset="UTF-8"))))
        if recipients:
            recipient_keys = [(field, value) for value in recipients for field in ("TO", "CC")]
            recipient_uids = set(self._search([*base, *_or_pairs(recipient_keys)], charset="UTF-8"))
            groups.append(("收件人/Cc", recipient_uids))
        if keywords:
            subject_uids = set(self._search([*base, *_or_search_keys("SUBJECT", keywords)], charset="UTF-8"))
            groups.append(("主题/正文关键词", subject_uids))
        address_groups = [values for label, values in groups if label != "主题/正文关键词"]
        if keywords and match_mode == "any":
            # 正文可能命中而主题不命中，因此保留日期范围内的 UID，再读取小预览判断。
            uids = date_uids
        elif keywords and match_mode == "all":
            # 地址组可以先安全缩小范围；关键词仍需在小预览中检查正文。
            uids = set.intersection(*address_groups) if address_groups else date_uids
        elif groups and match_mode == "all":
            uids = set.intersection(*(values for _label, values in groups))
        elif groups:
            uids = set.union(*(values for _label, values in groups))
        else:
            uids = date_uids
        ordered = _newest_first(uids)
        if maximum > 0:
            ordered = ordered[:maximum]
        reasons = {
            uid: [label for label, values in groups if uid in values]
            for uid in ordered
        }
        return ordered, reasons

    def _search(self, criteria: list[object], charset: str | None = None) -> list[str]:
        args: list[object] = []
        if charset:
            args.extend(("CHARSET", charset))
        args.extend(criteria)
        status, payload = self._require().uid("search", *args)
        if status != "OK":
            raise RuntimeError(f"IMAP 服务器端筛选失败：{status} {payload!r}")
        raw = payload[0] if payload else b""
        return [item.decode("ascii") for item in raw.split()]

    def fetch_message(self, uid: str) -> bytes:
        status, payload = self._require().uid("fetch", uid, "(RFC822)")
        if status != "OK":
            if _is_fetch_volume_limit(payload):
                raise FetchVolumeLimitError("126 IMAP FETCH 下载流量已达到阶段性上限")
            raise RuntimeError(f"下载邮件失败：folder={self.selected_mailbox} uid={uid} status={status}")
        for item in payload or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise RuntimeError(f"服务器未返回邮件正文：folder={self.selected_mailbox} uid={uid}")

    def fetch_message_preview(self, uid: str, max_bytes: int = 128 * 1024) -> bytes:
        """只读取邮件开头片段，用于地址、关键词和附件名筛选，避免下载大附件正文。"""
        status, payload = self._require().uid("fetch", uid, f"(BODY.PEEK[]<0.{max_bytes}>)")
        if status != "OK":
            if _is_fetch_volume_limit(payload):
                raise FetchVolumeLimitError("126 IMAP FETCH 下载流量已达到阶段性上限")
            raise RuntimeError(f"读取邮件预览失败：folder={self.selected_mailbox} uid={uid} status={status}")
        for item in payload or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise RuntimeError(f"服务器未返回邮件预览：folder={self.selected_mailbox} uid={uid}")

    def _send_client_id(self) -> None:
        client = self._require()
        imaplib.Commands["ID"] = ("AUTH", "SELECTED")
        values = []
        for key, value in self.settings.client_id.items():
            values.append(f'"{_id_escape(key)}" "{_id_escape(value)}"')
        status, response = client._simple_command("ID", "(" + " ".join(values) + ")")
        if status != "OK":
            logger.warning("126 IMAP ID 未被接受：%s %s", status, response)

    def _require(self) -> imaplib.IMAP4_SSL:
        if self._client is None:
            raise RuntimeError("IMAP 尚未连接")
        return self._client


def _imap_date(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{parsed.day:02d}-{months[parsed.month - 1]}-{parsed.year:04d}"


def _date_criteria(since: str, before: str) -> list[object]:
    criteria: list[object] = ["SINCE", _imap_date(since)] if since else ["ALL"]
    if before:
        criteria.extend(("BEFORE", _imap_date(before)))
    return criteria


def _quoted_utf8(value: str) -> bytes:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return b'"' + escaped.encode("utf-8") + b'"'


def _or_search_keys(field: str, values: tuple[str, ...]) -> list[object]:
    return _or_pairs([(field, value) for value in values])


def _or_pairs(values: list[tuple[str, str]]) -> list[object]:
    if not values:
        return ["ALL"]
    field, value = values[0]
    key: list[object] = [field, _quoted_utf8(value)]
    if len(values) == 1:
        return key
    return ["OR", *key, *_or_pairs(values[1:])]


def _newest_first(values: object) -> list[str]:
    return sorted((str(item) for item in values), key=lambda item: int(item), reverse=True)


def _first_ascii(payload: object) -> str:
    if isinstance(payload, (list, tuple)) and payload:
        return _first_ascii(payload[0])
    if isinstance(payload, bytes):
        return payload.decode("ascii", errors="ignore")
    return str(payload or "")


def _id_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_fetch_volume_limit(payload: object) -> bool:
    if isinstance(payload, (list, tuple)):
        return any(_is_fetch_volume_limit(item) for item in payload)
    if isinstance(payload, bytes):
        return b"fetch volume limit exceed" in payload.lower()
    return "fetch volume limit exceed" in str(payload).lower()


def _mask_email(value: str) -> str:
    local, separator, domain = value.partition("@")
    if not separator:
        return "***"
    return f"{local[:2]}***@{domain}"


def encode_modified_utf7(value: str) -> str:
    result: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        encoded = base64.b64encode("".join(buffer).encode("utf-16be")).decode("ascii").rstrip("=").replace("/", ",")
        result.append("&" + encoded + "-")
        buffer.clear()

    for char in value:
        if " " <= char <= "~":
            flush()
            result.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush()
    return "".join(result)


def decode_modified_utf7(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "&":
            result.append(value[index])
            index += 1
            continue
        end = value.find("-", index)
        if end < 0:
            result.append(value[index:])
            break
        token = value[index + 1 : end]
        if not token:
            result.append("&")
        else:
            token = token.replace(",", "/")
            token += "=" * ((4 - len(token) % 4) % 4)
            result.append(base64.b64decode(token).decode("utf-16be"))
        index = end + 1
    return "".join(result)
