"""Mail Storyline Tracker 图形界面入口

用途：
  启动 126.com 邮件筛选、增量下载、AI 工作事项梳理与时间线查看桌面界面。

配置文件：
  固定读取根目录 config.yaml；真实邮箱账号、客户端授权码和 AI API Key 写入被 Git 忽略的 .env。

必填参数：
  无。筛选条件可在 config.yaml 中设置，也可在界面中临时修改。

示例：
  python main.py

输出：
  原始邮件及结构化 JSON 写入 data/；邮件审核页和事项时间线写入 output/；日志写入 logs/main.log。
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from logging_config import configure_utf8_stdio, setup_logger
from mail_storyline_tracker.config import bootstrap
from mail_storyline_tracker.gui.app import run


def main() -> int:
    configure_utf8_stdio()
    ctx = bootstrap(PROJECT_ROOT)
    setup_logger(ctx.config.get("app", {}).get("log_level", "INFO"))
    root = tk.Tk()
    run(root, ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
