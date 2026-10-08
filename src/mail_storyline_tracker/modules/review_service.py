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
from .event_links import EventLinkStore


logger = logging.getLogger(__name__)


class ReviewService:
    def __init__(
        self,
        data_dir: Path,
        on_change: Callable[[], None] | None = None,
        *,
        page_path: Path | None = None,
        storyline_path: Path | None = None,
    ) -> None:
        token = secrets.token_urlsafe(24)
        lock = threading.Lock()
        origin = ""

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                logger.debug("审核接口：" + format, *args)

            def _allowed_origin(self) -> bool:
                return self.headers.get("Origin", "") in {"", "null", origin}

            def _authorized(self, path: str, expected_path: str, query: str) -> bool:
                supplied = parse_qs(query).get("token", [""])[0]
                return (
                    self._allowed_origin()
                    and path == expected_path
                    and secrets.compare_digest(supplied, token)
                )

            def do_GET(self) -> None:
                url = urlsplit(self.path)
                if self._authorized(url.path, "/review", url.query):
                    self._send(200, {"excluded_record_ids": sorted(ArchiveStore(data_dir).excluded_record_ids())})
                    return
                page = None
                if page_path is not None and self._authorized(url.path, "/page", url.query):
                    page = page_path
                elif storyline_path is not None and self._authorized(url.path, "/storyline", url.query):
                    page = storyline_path
                if page is None:
                    self._send(403, {"error": "审核页面连接无效"})
                    return
                try:
                    raw = page.read_bytes()
                except OSError:
                    logger.exception("读取本地审核页失败")
                    self._send(500, {"error": "读取本地审核页失败"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(raw)

            def _send(self, status: int, body: dict[str, object]) -> None:
                raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
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
                if self._authorized(url.path, "/event-link", url.query):
                    self._save_event_link()
                    return
                if not self._authorized(url.path, "/review", url.query):
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
                    if action not in {"merge", "exclude", "restore", "save"}:
                        raise ValueError("审核请求内容不正确")
                    field_names = ("exclude_ids", "restore_ids") if action == "save" else ("record_ids",)
                    fields = [request.get(name) for name in field_names]
                    if any(not isinstance(items, list) or len(items) > 5000 for items in fields):
                        raise ValueError("审核请求内容不正确")
                    if any(not isinstance(value, str) or not value or len(value) > 200 for items in fields for value in items):
                        raise ValueError("审核记录标识不正确")
                    with lock:
                        store = ArchiveStore(data_dir)
                        known = {str(record.get("record_id", "")) for record in store.records()}
                        if action == "save":
                            exclude_ids, restore_ids = (set(items) for items in fields)
                        else:
                            requested = set(fields[0])
                            if action == "merge":
                                requested &= known
                            exclude_ids = requested if action != "restore" else set()
                            restore_ids = requested if action == "restore" else set()
                        before = store.excluded_record_ids()
                        excluded = store.apply_review_decisions(exclude_ids, restore_ids)
                        store.delete_excluded_content()
                        report_error = False
                        if excluded != before and on_change:
                            try:
                                on_change()
                            except Exception:
                                report_error = True
                                logger.exception("审核决定已保存，但故事线报告重建失败")
                        logger.info("审核决定已保存：action=%s changed=%s excluded_total=%s", action, len(excluded ^ before), len(excluded))
                    self._send(200, {"excluded_record_ids": sorted(excluded), "report_error": report_error})
                except (ValueError, KeyError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)})
                except Exception:
                    logger.exception("保存审核决定失败")
                    self._send(500, {"error": "保存审核决定失败"})

            def _save_event_link(self) -> None:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 4096:
                        raise ValueError("链路审核请求大小不正确")
                    request = json.loads(self.rfile.read(size))
                    if not isinstance(request, dict):
                        raise ValueError("链路审核请求内容不正确")
                    target, source, dest, decision = (request.get(key) for key in ("target", "from_record_id", "to_record_id", "decision"))
                    if any(not isinstance(value, str) or not value or len(value) > 500 for value in (target, source, dest)):
                        raise ValueError("链路标识不正确")
                    if decision not in {"approved", "rejected"}:
                        raise ValueError("链路审核决定不正确")
                    with lock:
                        if storyline_path is None:
                            raise ValueError("尚未生成沟通链路报告")
                        report = json.loads(storyline_path.with_suffix(".json").read_text(encoding="utf-8"))
                        valid = any(
                            item.get("target") == target and any(
                                edge.get("from_record_id") == source and edge.get("to_record_id") == dest
                                for edge in item.get("edges", [])
                            ) for item in report.get("targets", [])
                        )
                        if not valid:
                            raise ValueError("这条候选连线不存在于当前报告")
                        EventLinkStore(data_dir).save(target, source, dest, decision)
                        report_error = False
                        if on_change:
                            try:
                                on_change()
                            except Exception:
                                report_error = True
                                logger.exception("链路审核已保存，但报告重建失败")
                    logger.info("事件链路人工审核已保存：decision=%s", decision)
                    self._send(200, {"saved": True, "report_error": report_error})
                except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
                    self._send(400, {"error": str(exc)})
                except Exception:
                    logger.exception("保存事件链路审核失败")
                    self._send(500, {"error": "保存事件链路审核失败"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="mail-review-service")
        self.thread.start()
        self.url = f"{origin}/review?token={token}"
        self.page_url = f"{origin}/page?token={token}"
        self.storyline_url = f"{origin}/storyline?token={token}"
        self.event_link_url = f"{origin}/event-link?token={token}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
