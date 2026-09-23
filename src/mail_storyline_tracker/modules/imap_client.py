from __future__ import annotations

import base64
import imaplib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from .mail_settings import MailSettings


logger = logging.getLogger(__name__)


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
        self._client = imaplib.IMAP4_SSL(self.settings.host, self.settings.port, timeout=30)
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
            except imaplib.IMAP4.error:
                pass
        try:
            client.logout()
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
        criteria = ["SINCE", _imap_date(since)] if since else ["ALL"]
        if before:
            criteria.extend(["BEFORE", _imap_date(before)])
        status, payload = self._require().uid("search", None, *criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP 搜索失败：{status} {payload!r}")
        raw = payload[0] if payload else b""
        uids = [item.decode("ascii") for item in reversed(raw.split())]
        return uids[:maximum] if maximum > 0 else uids

    def fetch_message(self, uid: str) -> bytes:
        status, payload = self._require().uid("fetch", uid, "(RFC822)")
        if status != "OK":
            raise RuntimeError(f"下载邮件失败：folder={self.selected_mailbox} uid={uid} status={status}")
        for item in payload or []:
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                return item[1]
        raise RuntimeError(f"服务器未返回邮件正文：folder={self.selected_mailbox} uid={uid}")

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


def _first_ascii(payload: object) -> str:
    if isinstance(payload, (list, tuple)) and payload:
        return _first_ascii(payload[0])
    if isinstance(payload, bytes):
        return payload.decode("ascii", errors="ignore")
    return str(payload or "")


def _id_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
