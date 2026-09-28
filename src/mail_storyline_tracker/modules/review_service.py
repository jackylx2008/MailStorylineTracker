"""将本地审核页的排除决定写入项目状态，不接触邮箱服务器。"""

from __future__ import annotations

import json
import logging
import secrets
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .storage import ArchiveStore


logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(self, data_dir: Path, on_change: Callable[[], None] | None = None) -> None:
        token = secrets.token_urlsafe(24)
        lock = threading.Lock()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                logger.debug("审核接口：" + format, *args)

            def _allowed_origin(self) -> bool:
                return self.headers.get("Origin", "") in {"", "null"}

            def _send(self, status: int, body: dict[str, object]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                if self.headers.get("Origin") == "null":
                    self.send_header("Access-Control-Allow-Origin", "null")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()
                self.wfile.write(raw)

            def do_OPTIONS(self) -> None:
                if not self._allowed_origin():
                    self._send(403, {"error": "不允许的页面来源"})
                    return
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()

            def do_POST(self) -> None:
                url = urlsplit(self.path)
                supplied = parse_qs(url.query).get("token", [""])[0]
                if not self._allowed_origin() or url.path != "/review" or not secrets.compare_digest(supplied, token):
                    self._send(403, {"error": "审核页面连接无效"})
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 262144:
                        raise ValueError("审核请求大小不正确")
                    request = json.loads(self.rfile.read(size))
                    if not isinstance(request, dict):
                        raise ValueError("审核请求内容不正确")
                    action = request.get("action")
                    ids = request.get("record_ids")
                    if action not in {"merge", "exclude", "restore"} or not isinstance(ids, list) or len(ids) > 5000:
                        raise ValueError("审核请求内容不正确")
                    if any(not isinstance(value, str) or not value or len(value) > 200 for value in ids):
                        raise ValueError("审核记录标识不正确")
                    with lock:
                        store = ArchiveStore(data_dir)
                        known = {str(record.get("record_id", "")) for record in store.records()}
                        requested = set(ids)
                        if action == "merge":
                            requested &= known
                        elif requested - known:
                            raise ValueError("审核记录不存在")
                        before = store.excluded_record_ids()
                        excluded = store.update_review_exclusions(requested, excluded=action != "restore")
                        report_error = False
                        if excluded != before and on_change:
                            try:
                                on_change()
                            except Exception:
                                report_error = True
                                logger.exception("审核决定已保存，但故事线报告重建失败")
                    self._send(200, {"excluded_record_ids": sorted(excluded), "report_error": report_error})
                except (ValueError, KeyError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)})
                except Exception:
                    logger.exception("保存审核决定失败")
                    self._send(500, {"error": "保存审核决定失败"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="mail-review-service")
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/review?token={token}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
