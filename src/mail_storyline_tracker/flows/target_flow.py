from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..config import AppContext
from ..modules.ai_client import AISettings, OpenAICompatibleClient
from ..modules.html_report import write_target_mindmap
from ..modules.imap_client import FetchVolumeLimitError, Imap126Client, is_imap_connection_error
from ..modules.mail_parser import parse_message
from ..modules.mail_settings import MailSettings
from ..modules.storage import ArchiveStore
from ..modules.target_config import TargetCriteria
from ..modules.threading import group_conversations


logger = logging.getLogger(__name__)
Progress = Callable[[str, int, int], None]
TARGET_SCAN_BATCH_SIZE = 10
TARGET_SCAN_PREVIEW_BYTES = 128 * 1024


def scan_targets(
    ctx: AppContext,
    progress: Progress | None = None,
    criteria: TargetCriteria | None = None,
) -> dict[str, Any]:
    criteria = criteria or TargetCriteria.load(ctx.project_root)
    settings = MailSettings.from_config(ctx.config)
    ai = OpenAICompatibleClient(AISettings.from_config(ctx.config))
    store = ArchiveStore(ctx.data_dir)
    blocked_until = store.fetch_blocked_until(settings.user)
    if blocked_until:
        reason = f"126 官方建议流量超限后间隔 24 小时再试；本地保护暂停至 {blocked_until}"
        logger.warning(reason)
        return generate_target_report(
            ctx,
            criteria,
            {"incomplete": True, "stop_reason": reason, "errors": [{"mailbox": "", "uid": "", "error": reason}]},
        )
    ai.check()
    batch: list[tuple[str, bytes, dict[str, Any]]] = []
    skipped = 0
    checked = 0
    saved = 0
    volume_limited = False
    interrupted = False
    budget_reached = False
    stop_reason = ""
    errors: list[dict[str, str]] = []

    with Imap126Client(settings) as client:
        mailboxes = [item for item in client.list_mailboxes() if not _has_noselect(item.flags)]
        total_folders = len(mailboxes)
        for folder_index, mailbox in enumerate(mailboxes, start=1):
            if checked >= settings.max_messages_per_run:
                budget_reached = True
                break
            try:
                _count, uidvalidity = client.select_mailbox(mailbox.name)
                uids = client.search_uids(settings.since, settings.before, 0)
            except Exception as exc:
                logger.exception("无法扫描邮箱文件夹：%s", mailbox.name)
                errors.append({"mailbox": mailbox.name, "uid": "", "error": f"{type(exc).__name__}: {exc}"})
                if is_imap_connection_error(exc):
                    interrupted = True
                    break
                continue
            folder_checked = 0
            for message_index, uid in enumerate(uids, start=1):
                key = store.state_key(settings.user, mailbox.name, uidvalidity, uid)
                if store.is_processed(key, criteria.signature):
                    skipped += 1
                    continue
                if checked >= settings.max_messages_per_run:
                    budget_reached = True
                    break
                if folder_checked >= settings.max_messages_per_folder:
                    break
                folder_checked += 1
                if progress:
                    progress(f"{mailbox.name} UID {uid}", message_index, len(uids))
                try:
                    raw = client.fetch_message_preview(uid, TARGET_SCAN_PREVIEW_BYTES)
                    if progress:
                        progress(f"{mailbox.name} UID {uid}", message_index, len(uids))
                    record = parse_message(
                        raw,
                        account=settings.user,
                        mailbox=mailbox.name,
                        uidvalidity=uidvalidity,
                        uid=uid,
                    )
                    record["source_truncated"] = True
                    batch.append((key, raw, record))
                    checked += 1
                    if len(batch) >= TARGET_SCAN_BATCH_SIZE:
                        saved += _process_batch(batch, store, criteria, ai)
                        batch.clear()
                    if message_index == 1 or message_index == len(uids) or message_index % 25 == 0:
                        logger.info(
                            "目标扫描邮件进度：folder=%s %s/%s checked=%s saved=%s skipped=%s",
                            mailbox.name,
                            message_index,
                            len(uids),
                            checked,
                            saved,
                            skipped,
                        )
                except FetchVolumeLimitError as exc:
                    volume_limited = True
                    blocked_until = store.mark_fetch_limited(settings.user, settings.volume_limit_cooldown_hours)
                    logger.warning("目标扫描因 126 下载流量限制暂停：folder=%s uid=%s", mailbox.name, uid)
                    errors.append({
                        "mailbox": mailbox.name,
                        "uid": uid,
                        "error": f"{exc}；本地保护暂停至 {blocked_until}",
                    })
                    break
                except Exception as exc:
                    logger.exception("邮件处理失败：folder=%s uid=%s", mailbox.name, uid)
                    errors.append({"mailbox": mailbox.name, "uid": uid, "error": f"{type(exc).__name__}: {exc}"})
                    if is_imap_connection_error(exc):
                        interrupted = True
                        break
            if batch:
                saved += _process_batch(batch, store, criteria, ai)
                batch.clear()
            logger.info("目标扫描进度：文件夹 %s/%s %s", folder_index, total_folders, mailbox.name)
            if volume_limited or interrupted or budget_reached:
                break

    store.flush()
    if volume_limited:
        stop_reason = f"126 IMAP FETCH 下载流量已达到阶段性上限；依据官方建议暂停至 {blocked_until}"
    elif interrupted:
        stop_reason = "IMAP 连接中断；已保存完成进度，下次运行将断点续传"
    elif budget_reached:
        stop_reason = f"已达单次运行保守上限 {settings.max_messages_per_run} 封；可再次运行继续"
    return generate_target_report(
        ctx,
        criteria,
        {
            "folders_discovered": total_folders,
            "new_messages_checked": checked,
            "new_messages_saved": saved,
            "incremental_skipped": skipped,
            "incomplete": volume_limited or interrupted or budget_reached,
            "stop_reason": stop_reason,
            "errors": errors,
        },
    )


def generate_target_report(
    ctx: AppContext,
    criteria: TargetCriteria | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    criteria = criteria or TargetCriteria.load(ctx.project_root)
    store = ArchiveStore(ctx.data_dir)
    result = build_target_storylines(store.records(), criteria)
    result.update({"generated_at": datetime.now(timezone.utc).isoformat(), **(run_metadata or {})})
    output_json = ctx.output_dir / "target_storylines.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    output_html = write_target_mindmap(result, ctx.output_dir / "target_storylines.html")
    return {"json": str(output_json), "html": str(output_html), "summary": _summary(result)}


def _process_batch(
    batch: list[tuple[str, bytes, dict[str, Any]]],
    store: ArchiveStore,
    criteria: TargetCriteria,
    ai: OpenAICompatibleClient,
) -> int:
    filenames = [item["filename"] for _, _, record in batch for item in record.get("attachments", [])]
    filename_matches = ai.match_attachment_names(filenames, list(criteria.files))
    saved = 0
    for key, raw, record in batch:
        reasons = _or_match_reasons(record, criteria, filename_matches)
        record["matched_by"] = reasons
        record["target_matches"] = _record_target_matches(record, filename_matches)
        if reasons:
            stored = store.save_message(raw, record)
            saved += 1
            status = "saved"
            record_id = stored["record_id"]
        else:
            status = "not_matched"
            record_id = ""
        store.mark(
            key,
            message_id=record["message_id"],
            content_sha256=record["content_sha256"],
            status=status,
            filter_signature=criteria.signature,
            record_id=record_id,
        )
    store.flush()
    return saved


def build_target_storylines(records: list[dict[str, Any]], criteria: TargetCriteria) -> dict[str, Any]:
    conversations = group_conversations(records)
    by_record: dict[str, dict[str, Any]] = {}
    for conversation in conversations:
        for record in conversation["messages"]:
            by_record[record["record_id"]] = conversation
    targets = []
    all_related: set[str] = set()
    for target in criteria.files:
        seeds = {
            record["record_id"]
            for record in records
            if any(item.get("target") == target for item in record.get("target_matches", []))
        }
        related: dict[str, dict[str, Any]] = {}
        for record_id in seeds:
            conversation = by_record.get(record_id)
            if conversation:
                for message in conversation["messages"]:
                    related[message["record_id"]] = message
            else:
                record = next((item for item in records if item["record_id"] == record_id), None)
                if record:
                    related[record_id] = record
        ordered = sorted(related.values(), key=lambda item: item.get("sent_at", ""))
        all_related.update(related)
        attachment_names = sorted(
            {
                item.get("filename", "")
                for record in ordered
                for item in record.get("attachments", [])
                if any(match.get("target") == target for match in record.get("target_matches", []))
            }
        )
        targets.append(
            {
                "target": target,
                "attachment_names": attachment_names,
                "events": [_event(record, target) for record in ordered],
            }
        )
    return {"targets": targets, "matched_messages": len(all_related), "archived_messages": len(records)}


def _or_match_reasons(record: dict[str, Any], criteria: TargetCriteria, filename_matches: dict[str, list[dict[str, Any]]]) -> list[str]:
    reasons: list[str] = []
    address_text = " ".join(
        value
        for group in record.get("addresses", {}).values()
        for value in group
    ).lower()
    attachment_names = [item.get("filename", "") for item in record.get("attachments", [])]
    keyword_text = "\n".join([record.get("subject", ""), record.get("body_text", ""), *attachment_names]).lower()
    if any(value.lower() in address_text for value in criteria.emails):
        reasons.append("目标联系人")
    if any(value.lower() in keyword_text for value in criteria.keywords):
        reasons.append("目标关键词")
    if any(filename_matches.get(name) for name in attachment_names):
        reasons.append("目标附件名（本地 AI 模糊匹配）")
    return reasons


def _record_target_matches(record: dict[str, Any], filename_matches: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    result = []
    for attachment in record.get("attachments", []):
        filename = attachment.get("filename", "")
        for match in filename_matches.get(filename, []):
            result.append({"filename": filename, **match})
    return result


def _event(record: dict[str, Any], target: str) -> dict[str, Any]:
    target_attachments = [
        item.get("filename", "")
        for item in record.get("target_matches", [])
        if item.get("target") == target
    ]
    return {
        "record_id": record.get("record_id", ""),
        "sent_at": record.get("sent_at", ""),
        "from": record.get("from", ""),
        "to": record.get("to", ""),
        "cc": record.get("cc", ""),
        "subject": record.get("subject", ""),
        "action": _communication_action(record, target_attachments),
        "attachments": target_attachments,
        "match_reasons": record.get("matched_by", []),
        "mailbox": record.get("mailbox", ""),
        "uid": record.get("uid", ""),
    }


def _communication_action(record: dict[str, Any], target_attachments: list[str]) -> str:
    text = f"{record.get('subject', '')}\n{record.get('body_text', '')[:500]}"
    if target_attachments and any(word in text for word in ("更新", "修订", "修改")):
        return "发送更新文件"
    if target_attachments:
        return "发送目标附件"
    for keyword, action in (("确认", "确认/认可"), ("回复", "回复意见"), ("审核", "反馈审核意见"), ("意见", "沟通意见"), ("提交", "提交资料")):
        if keyword in text:
            return action
    return "往来沟通"


def _has_noselect(flags: tuple[str, ...]) -> bool:
    return any(flag.lower() == "\\noselect" for flag in flags)


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "targets": len(result["targets"]),
        "targets_with_events": sum(1 for item in result["targets"] if item["events"]),
        "matched_messages": result["matched_messages"],
        "folders_discovered": result.get("folders_discovered", 0),
        "new_messages_saved": result.get("new_messages_saved", 0),
        "incomplete": result.get("incomplete", False),
        "errors": len(result.get("errors", [])),
    }
