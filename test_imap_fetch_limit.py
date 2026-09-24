"""最小化检查 126 IMAP 是否仍处于 FETCH 下载流量限制状态。

默认只读打开 INBOX，并读取最新一封邮件的前 1 KB；不会输出邮件内容，
不会下载附件，也不会删除、移动、标记或修改服务器邮件。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mail_storyline_tracker.config import bootstrap
from mail_storyline_tracker.modules.imap_client import FetchVolumeLimitError, Imap126Client
from mail_storyline_tracker.modules.mail_settings import MailSettings
from mail_storyline_tracker.modules.storage import ArchiveStore
from logging_config import configure_utf8_stdio


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", default="INBOX", help="只读测试的邮箱文件夹，默认 INBOX")
    parser.add_argument("--bytes", type=int, default=1024, help="读取的最大字节数，默认 1024")
    parser.add_argument("--force", action="store_true", help="忽略本地24小时冷却，强制执行一次真实 FETCH 测试")
    return parser.parse_args()


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    if args.bytes <= 0 or args.bytes > 16 * 1024:
        raise ValueError("--bytes 必须在 1 到 16384 之间")

    result: dict[str, object] = {
        "tested_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "folder": args.folder,
        "requested_bytes": args.bytes,
    }
    try:
        ctx = bootstrap(PROJECT_ROOT)
        settings = MailSettings.from_config(ctx.config)
        store = ArchiveStore(ctx.data_dir)
        blocked_until = store.fetch_blocked_until(settings.user)
        if blocked_until and not args.force:
            result.update({
                "status": "limited",
                "fetch": "skipped_by_local_cooldown",
                "blocked_until": blocked_until,
                "message": "依据126官方建议，流量超限后24小时内不再执行FETCH；可用--force强制实测一次",
            })
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        with Imap126Client(settings) as client:
            total, _uidvalidity = client.select_mailbox(args.folder)
            result.update({"login": "ok", "message_count": total})
            uids = client.search_uids("", "", 1)
            if not uids:
                result.update({"status": "ok", "fetch": "no_messages"})
            else:
                payload = client.fetch_message_preview(uids[0], args.bytes)
                result.update({"status": "ok", "fetch": "ok", "received_bytes": len(payload)})
    except FetchVolumeLimitError as exc:
        blocked_until = store.mark_fetch_limited(settings.user, settings.volume_limit_cooldown_hours)
        store.flush()
        result.update({
            "status": "limited",
            "fetch": "volume_limited",
            "blocked_until": blocked_until,
            "message": str(exc),
        })
    except Exception as exc:
        result.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 2 if result.get("status") == "limited" else 1


if __name__ == "__main__":
    raise SystemExit(main())
