from __future__ import annotations

import hashlib
import html
import re
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage, Message
from email.policy import default
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any


def parse_message(raw_bytes: bytes, *, account: str, mailbox: str, uidvalidity: str, uid: str) -> dict[str, Any]:
    parsed = message_from_bytes(raw_bytes, policy=default)
    if not isinstance(parsed, EmailMessage):
        raise ValueError("无法按 EmailMessage 解析邮件")
    headers = {name: _header(parsed, name) for name in ("date", "from", "to", "cc", "subject", "message-id", "in-reply-to", "references")}
    sent_at = _parse_date(headers["date"])
    body = _extract_body(parsed)
    attachments = []
    for index, part in enumerate(_attachment_parts(parsed), start=1):
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            {
                "filename": safe_filename(_decode(part.get_filename() or f"attachment_{index}{_extension(part)}")),
                "content_type": part.get_content_type(),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "_payload": payload,
            }
        )
    addresses = {
        "from": _addresses(headers["from"]),
        "to": _addresses(headers["to"]),
        "cc": _addresses(headers["cc"]),
    }
    digest = hashlib.sha256(raw_bytes).hexdigest()
    message_id = headers["message-id"].strip()
    stable_id = hashlib.sha256((message_id.lower() if message_id else digest).encode("utf-8")).hexdigest()[:24]
    return {
        "record_id": stable_id,
        "account": account,
        "mailbox": mailbox,
        "uidvalidity": uidvalidity,
        "uid": uid,
        "message_id": message_id,
        "in_reply_to": _message_ids(headers["in-reply-to"]),
        "references": _message_ids(headers["references"]),
        "sent_at": sent_at,
        "from": headers["from"],
        "to": headers["to"],
        "cc": headers["cc"],
        "addresses": addresses,
        "subject": headers["subject"],
        "body_text": body,
        "attachments": attachments,
        "content_sha256": digest,
        "raw_headers": headers,
        "eml_path": "",
        "matched_by": [],
    }


def matches_filters(record: dict[str, Any], senders: tuple[str, ...], recipients: tuple[str, ...], keywords: tuple[str, ...], mode: str) -> tuple[bool, list[str]]:
    checks: list[tuple[str, bool]] = []
    from_text = " ".join(record["addresses"]["from"] + [record["from"]]).lower()
    recipient_text = " ".join(record["addresses"]["to"] + record["addresses"]["cc"] + [record["to"], record["cc"]]).lower()
    keyword_text = f"{record['subject']}\n{record['body_text']}".lower()
    if senders:
        checks.append(("发件人", any(item.lower() in from_text for item in senders)))
    if recipients:
        checks.append(("收件人/Cc", any(item.lower() in recipient_text for item in recipients)))
    if keywords:
        checks.append(("主题/正文关键词", any(item.lower() in keyword_text for item in keywords)))
    if not checks:
        return True, ["未设置筛选条件"]
    matched = all(value for _, value in checks) if mode == "all" else any(value for _, value in checks)
    return matched, [name for name, value in checks if value]


def attachment_payloads(record: dict[str, Any]) -> list[tuple[str, bytes]]:
    return [(item["filename"], item.get("_payload", b"")) for item in record.get("attachments", [])]


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    clean = dict(record)
    clean["attachments"] = [{key: value for key, value in item.items() if key != "_payload"} for item in record.get("attachments", [])]
    return clean


def _header(message: Message, name: str) -> str:
    value = message.get(name, "")
    return _decode(value)


def _decode(value: object) -> str:
    raw = str(value).replace("\r", " ").replace("\n", " ")
    try:
        decoded = str(make_header(decode_header(raw)))
    except Exception:
        decoded = raw
    return re.sub(r"\s+", " ", decoded).strip()


def _parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.isoformat()
    except (TypeError, ValueError):
        return value


def _addresses(value: str) -> list[str]:
    return [address.lower() for _, address in getaddresses([value]) if address]


def _message_ids(value: str) -> list[str]:
    return re.findall(r"<[^>]+>", value)


def _extract_body(message: EmailMessage) -> str:
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        texts = [_part_text(part) for part in message.walk() if part.get_content_maintype() == "text" and not _is_attachment(part)]
        return _normalize("\n".join(texts))
    text = _part_text(body)
    return _html_to_text(text) if body.get_content_subtype() == "html" else _normalize(text)


def _part_text(part: Message) -> str:
    try:
        return str(part.get_content())
    except Exception:
        raw = part.get_payload(decode=True) or b""
        return raw.decode(part.get_content_charset() or "utf-8", errors="replace")


def _html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    value = re.sub(r"(?i)<br\s*/?>|</(?:p|div|tr|li|h[1-6])>", "\n", value)
    return _normalize(html.unescape(re.sub(r"(?s)<[^>]+>", " ", value)))


def _normalize(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _attachment_parts(message: EmailMessage) -> list[Message]:
    return [part for part in message.walk() if not part.is_multipart() and _is_attachment(part)]


def _is_attachment(part: Message) -> bool:
    return bool(part.get_filename()) or (part.get_content_disposition() or "").lower() == "attachment"


def _extension(part: Message) -> str:
    return {"application/pdf": ".pdf", "text/plain": ".txt"}.get(part.get_content_type().lower(), ".bin")


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", Path(value).name.strip())
    return cleaned.strip(" .") or "attachment"
