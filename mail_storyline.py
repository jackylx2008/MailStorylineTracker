"""邮件事项时间线命令行工具

用途：
  检查 126.com IMAP 与 AI 服务、预览筛选结果、增量下载邮件，并生成工作事项时间线。

配置文件：
  默认读取根目录 config.yaml；真实邮箱、授权码及 AI API Key 写入不受 Git 跟踪的 .env。

示例：
  python mail_storyline.py check-mail
  python mail_storyline.py list-folders
  python mail_storyline.py preview --senders example.com --keywords 项目,合同
  python mail_storyline.py download
  python mail_storyline.py analyze

输出：
  原始邮件和 JSON 状态写入 data/，审核与时间线页面写入 output/，日志写入 logs/。
"""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("check-login", "check-mail", "list-folders", "preview", "download", "check-ai", "analyze", "all"))
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--folders", help="逗号分隔的邮箱文件夹")
    parser.add_argument("--senders", help="逗号分隔的发件人地址或片段")
    parser.add_argument("--recipients", help="逗号分隔的收件人/Cc 地址或片段")
    parser.add_argument("--keywords", help="逗号分隔的主题/正文关键词")
    parser.add_argument("--match-mode", choices=("any", "all"))
    parser.add_argument("--since", help="起始日期 YYYY-MM-DD")
    parser.add_argument("--before", help="结束日期 YYYY-MM-DD，不含当日")
    return parser.parse_args()


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    ctx = bootstrap(PROJECT_ROOT, args.config)
    setup_logger(ctx.config.get("app", {}).get("log_level", "INFO"))
    overrides = {key: value for key, value in vars(args).items() if key in {"folders", "senders", "recipients", "keywords", "match_mode", "since", "before"} and value is not None}
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
    elif args.action == "check-ai":
        result = check_ai(ctx)
    elif args.action == "analyze":
        result = analyze(ctx)
    else:
        result = {"download": download(ctx, overrides), "analysis": analyze(ctx)}
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
