"""按保守批次推进完整邮件归档队列。

队列：
- acoustics：完整归档“声学”文件夹全部邮件及附件。
- sent：完整归档“已发送”文件夹全部邮件及附件。
- target-email：在全部文件夹中完整归档 target_email.env 地址涉及的邮件及附件。
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
from mail_storyline_tracker.flows.mail_flow import download, list_folders
from mail_storyline_tracker.modules.target_config import TargetCriteria


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("queue", choices=("acoustics", "sent", "target-email"))
    parser.add_argument("--batch", type=int, default=5, help="本轮最多新下载数，默认5，上限50")
    return parser.parse_args()


def main() -> int:
    configure_utf8_stdio()
    args = parse_args()
    if args.batch <= 0 or args.batch > 50:
        raise ValueError("--batch 必须在1到50之间")
    ctx = bootstrap(PROJECT_ROOT)
    setup_logger(ctx.config.get("app", {}).get("log_level", "INFO"))
    common = {
        "since": "",
        "before": "",
        "keywords": (),
        "match_mode": "any",
        "max_messages_per_folder": args.batch,
        "max_messages_per_run": args.batch,
    }
    if args.queue == "acoustics":
        overrides = {**common, "folders": ("声学",), "senders": (), "recipients": ()}
    elif args.queue == "sent":
        overrides = {**common, "folders": ("已发送",), "senders": (), "recipients": ()}
    else:
        criteria = TargetCriteria.load(PROJECT_ROOT)
        overrides = {
            **common,
            "folders": tuple(list_folders(ctx)),
            "senders": criteria.emails,
            "recipients": criteria.emails,
        }
    result = download(ctx, overrides)
    result["queue"] = args.queue
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
