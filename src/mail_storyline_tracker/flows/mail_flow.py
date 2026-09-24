from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from ..config import AppContext
from ..modules.ai_client import AISettings, OpenAICompatibleClient
from ..modules.html_report import write_mail_review, write_storyline_report
from ..modules.imap_client import FetchVolumeLimitError, Imap126Client
from ..modules.mail_parser import matches_filters, parse_message
from ..modules.mail_settings import MailSettings
from ..modules.storage import ArchiveStore
from ..modules.threading import group_conversations


logger = logging.getLogger(__name__)
Progress = Callable[[str, int, int], None]
PREVIEW_BYTES = 16 * 1024


def check_login(ctx: AppContext) -> dict[str, Any]:
    """只验证 TLS、LOGIN 与 126 ID 握手，不列出或选择邮箱文件夹。"""
    settings = MailSettings.from_config(ctx.config)
    with Imap126Client(settings):
        pass
    return {"status": "ok", "account": _mask(settings.user), "mail_accessed": False}


def check_connection(ctx: AppContext, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    settings = MailSettings.from_config(ctx.config).with_overrides(overrides)
    with Imap126Client(settings) as client:
        folders = client.list_mailboxes()
    return {"status": "ok", "account": _mask(settings.user), "folders": [item.name for item in folders]}


def list_folders(ctx: AppContext) -> list[str]:
    return check_connection(ctx)["folders"]


def preview(ctx: AppContext, overrides: Mapping[str, Any] | None = None, progress: Progress | None = None) -> dict[str, Any]:
    return _scan(ctx, overrides, save=False, progress=progress)


def download(ctx: AppContext, overrides: Mapping[str, Any] | None = None, progress: Progress | None = None) -> dict[str, Any]:
    return _scan(ctx, overrides, save=True, progress=progress)


def _scan(ctx: AppContext, overrides: Mapping[str, Any] | None, *, save: bool, progress: Progress | None) -> dict[str, Any]:
    settings = MailSettings.from_config(ctx.config).with_overrides(overrides)
    store = ArchiveStore(ctx.data_dir)
    seen = matched = saved = skipped_incremental = 0
    preview_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    volume_limited = False
    with Imap126Client(settings) as client:
        for mailbox in settings.folders:
            try:
                count, uidvalidity = client.select_mailbox(mailbox)
                uids, server_reasons = client.search_filtered_uids(
                    settings.since,
                    settings.before,
                    settings.max_messages_per_folder,
                    settings.senders,
                    settings.recipients,
                    settings.keywords,
                    settings.match_mode,
                )
            except Exception as exc:
                logger.exception("无法筛选邮箱文件夹：%s", mailbox)
                errors.append({"mailbox": mailbox, "uid": "", "error": f"{type(exc).__name__}: {exc}"})
                continue
            logger.info("扫描文件夹=%s 邮件总数=%s 搜索范围=%s", mailbox, count, len(uids))
            for index, uid in enumerate(uids, start=1):
                key = store.state_key(settings.user, mailbox, uidvalidity, uid)
                if save and store.is_processed(key, settings.filter_signature):
                    skipped_incremental += 1
                    continue
                seen += 1
                if progress:
                    progress(f"{mailbox} UID {uid}", index, len(uids))
                try:
                    raw = client.fetch_message_preview(uid, PREVIEW_BYTES)
                    if progress:
                        progress(f"{mailbox} UID {uid}", index, len(uids))
                    record = parse_message(raw, account=settings.user, mailbox=mailbox, uidvalidity=uidvalidity, uid=uid)
                    is_match, reasons = matches_filters(record, settings.senders, settings.recipients, settings.keywords, settings.match_mode)
                    is_match, reasons = _merge_server_matches(is_match, reasons, server_reasons.get(uid, []), settings)
                    record["matched_by"] = reasons
                    preview_rows.append({
                        "uid": uid,
                        "mailbox": mailbox,
                        "sent_at": record["sent_at"],
                        "from": record["from"],
                        "to": record["to"],
                        "subject": record["subject"],
                        "matched": is_match,
                        "matched_by": reasons,
                    })
                    if is_match:
                        matched += 1
                    if save and is_match:
                        raw = client.fetch_message(uid)
                        record = parse_message(raw, account=settings.user, mailbox=mailbox, uidvalidity=uidvalidity, uid=uid)
                        _matched, full_reasons = matches_filters(
                            record,
                            settings.senders,
                            settings.recipients,
                            settings.keywords,
                            settings.match_mode,
                        )
                        _matched, reasons = _merge_server_matches(
                            _matched,
                            full_reasons,
                            server_reasons.get(uid, []),
                            settings,
                        )
                        record["matched_by"] = reasons
                        stored = store.save_message(raw, record)
                        saved += 1
                        store.mark(key, message_id=record["message_id"], content_sha256=record["content_sha256"], status="saved", filter_signature=settings.filter_signature, record_id=stored["record_id"])
                    elif save:
                        store.mark(key, message_id=record["message_id"], content_sha256=record["content_sha256"], status="not_matched", filter_signature=settings.filter_signature)
                except FetchVolumeLimitError as exc:
                    volume_limited = True
                    logger.warning("扫描因 126 下载流量限制暂停：folder=%s uid=%s", mailbox, uid)
                    errors.append({"mailbox": mailbox, "uid": uid, "error": f"{type(exc).__name__}: {exc}"})
                    break
                except Exception as exc:
                    logger.exception("邮件处理失败：folder=%s uid=%s", mailbox, uid)
                    errors.append({"mailbox": mailbox, "uid": uid, "error": f"{type(exc).__name__}: {exc}"})
            if volume_limited:
                break
    if save:
        store.flush()
        review_path = write_mail_review(store.records(), ctx.output_dir / "mail_review.html")
    else:
        review_path = None
    result = {
        "mode": "download" if save else "preview",
        "messages_checked": seen,
        "messages_matched": matched,
        "messages_saved": saved,
        "incremental_skipped": skipped_incremental,
        "errors": errors,
        "incomplete": volume_limited,
        "stop_reason": "126 IMAP FETCH 下载流量已达到阶段性上限" if volume_limited else "",
        "preview": preview_rows,
        "review_html": str(review_path) if review_path is not None else "",
    }
    logger.info("邮件扫描完成：%s", {key: value for key, value in result.items() if key != "preview"})
    return result


def check_ai(ctx: AppContext) -> dict[str, Any]:
    return OpenAICompatibleClient(AISettings.from_config(ctx.config)).check()


def analyze(ctx: AppContext) -> dict[str, Any]:
    store = ArchiveStore(ctx.data_dir)
    records = store.records()
    if not records:
        raise RuntimeError("尚无已下载邮件，请先执行下载归档")
    conversations = group_conversations(records)
    result = OpenAICompatibleClient(AISettings.from_config(ctx.config)).summarize(conversations)
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    result["conversation_count"] = len(conversations)
    result["message_count"] = len(records)
    output_json = ctx.output_dir / "storyline.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    output_html = write_storyline_report(result, ctx.output_dir / "storyline.html")
    return {"result": result, "json": str(output_json), "html": str(output_html)}


def _mask(value: str) -> str:
    local, _, domain = value.partition("@")
    return f"{local[:2]}***@{domain}" if domain else "***"


def _merge_server_matches(
    local_match: bool,
    local_reasons: list[str],
    server_reasons: list[str],
    settings: MailSettings,
) -> tuple[bool, list[str]]:
    reasons = list(dict.fromkeys([*local_reasons, *server_reasons]))
    active = []
    if settings.senders:
        active.append("发件人")
    if settings.recipients:
        active.append("收件人/Cc")
    if settings.keywords:
        active.append("主题/正文关键词")
    if not active:
        return True, reasons
    if settings.match_mode == "all":
        return all(label in reasons for label in active), reasons
    return local_match or any(label in reasons for label in active), reasons
