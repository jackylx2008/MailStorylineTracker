"""有关邮件下载与人工审核命令行工具。服务器只读，本地审核删除原文及附件。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from logging_config import configure_utf8_stdio, setup_logger
from mail_storyline_tracker.config import bootstrap
from mail_storyline_tracker.flows.mail_flow import analyze, check_ai, check_connection, check_login, download, list_folders, preview
from mail_storyline_tracker.flows.target_flow import classify_local_archive, generate_target_report, scan_targets
from mail_storyline_tracker.modules.target_config import TargetCriteria


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "action",
        choices=(
            "check-login", "check-mail", "list-folders", "preview", "download", "target-scan",
            "review", "purge-reviewed",
        ),
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--folders", help="逗号分隔的邮箱文件夹")
    parser.add_argument("--senders", help="逗号分隔的发件人地址或片段")
    parser.add_argument("--recipients", help="逗号分隔的收件人/Cc 地址或片段")
    parser.add_argument("--keywords", help="逗号分隔的主题/正文关键词")
    parser.add_argument("--match-mode", choices=("any", "all"))
    parser.add_argument("--since", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--before", help="结束日期 YYYY-MM-DD，不含当日")
    parser.add_argument("--max-messages-per-folder", type=int, help="每个文件夹最多检查的最新候选邮件数")
    return parser.parse_args()


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    ctx = bootstrap(PROJECT_ROOT, args.config)
    setup_logger(ctx.config.get("app", {}).get("log_level", "INFO"))
    overrides = {
        key: value
        for key, value in vars(args).items()
        if key in {
            "folders",
            "senders",
            "recipients",
            "keywords",
            "match_mode",
            "since",
            "before",
            "max_messages_per_folder",
        }
        and value is not None
    }
    if args.action == "check-login":
        result = check_login(ctx)
    elif args.action == "check-mail":
        result = check_connection(ctx, overrides)
    elif args.action == "list-folders":
        result = {"folders": list_folders(ctx)}
    elif args.action == "preview":
        result = preview(ctx, overrides)
    elif args.action == "download":
        result = download(ctx, overrides)
    elif args.action == "target-scan":
        result = scan_targets(ctx, overrides=overrides)
    else:
        from mail_storyline_tracker.modules.storage import ArchiveStore
        from mail_storyline_tracker.modules.html_report import write_mail_review
        store = ArchiveStore(ctx.data_dir)
        removed = store.delete_excluded_content() if args.action == "purge-reviewed" else 0
        result = {"deleted": removed, "retained": len(store.reviewed_records()), "html": str(write_mail_review(store.reviewed_records(), ctx.output_dir / "mail_review.html"))}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
