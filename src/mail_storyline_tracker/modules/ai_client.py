from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AISettings:
    base_url: str
    model: str
    api_key: str
    remote_enabled: bool
    timeout_seconds: int
    max_tokens: int
    temperature: float
    max_input_chars: int
    max_body_chars_per_message: int

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "AISettings":
        raw = config.get("ai", {})
        return cls(
            base_url=str(raw.get("base_url", "http://127.0.0.1:8080/v1")).rstrip("/"),
            model=str(raw.get("model", "local-model")),
            api_key=str(raw.get("api_key", "")),
            remote_enabled=bool(raw.get("remote_enabled", False)),
            timeout_seconds=int(raw.get("timeout_seconds", 300)),
            max_tokens=int(raw.get("max_tokens", 4096)),
            temperature=float(raw.get("temperature", 0)),
            max_input_chars=int(raw.get("max_input_chars", 60000)),
            max_body_chars_per_message=int(raw.get("max_body_chars_per_message", 6000)),
        )


class OpenAICompatibleClient:
    def __init__(self, settings: AISettings) -> None:
        self.settings = settings
        parsed = urlparse(settings.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("AI base_url 无效")
        local_hosts = {"127.0.0.1", "localhost", "::1"}
        if parsed.hostname.lower() not in local_hosts and not settings.remote_enabled:
            raise RuntimeError("远端 AI 默认关闭；只有 AI_REMOTE_ENABLED=true 时才允许发送邮件内容")

    def check(self) -> dict[str, Any]:
        try:
            models = self._request(f"{self.settings.base_url}/models")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("AI 服务要求鉴权，请在本地 .env 中配置 AI_API_KEY") from exc
            raise RuntimeError(f"AI 模型接口返回 HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"无法连接 AI 服务：{self.settings.base_url}；{exc.reason}") from exc
        ids = [str(item.get("id")) for item in models.get("data", []) if item.get("id")]
        selected = self.settings.model
        if selected not in ids and selected == "local-model" and len(ids) == 1:
            selected = ids[0]
        if ids and selected not in ids:
            raise RuntimeError(f"配置模型不可用：{self.settings.model}；可用模型：{ids}")
        return {"status": "ok", "models": ids, "resolved_model": selected}

    def summarize(self, conversations: list[dict[str, Any]]) -> dict[str, Any]:
        check = self.check()
        prompt = build_prompt(conversations, self.settings)
        payload = {
            "model": check["resolved_model"],
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": "你是严谨的中文工作邮件分析助手。只依据输入内容回答，不得臆测，并严格输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        response = self._request(f"{self.settings.base_url}/chat/completions", payload)
        content = str(response["choices"][0]["message"].get("content", ""))
        result = parse_json_response(content)
        if not isinstance(result.get("matters"), list):
            raise RuntimeError("AI 返回结果缺少 matters 数组")
        result["model"] = check["resolved_model"]
        return result

    def match_attachment_names(self, filenames: list[str], targets: list[str]) -> dict[str, list[dict[str, Any]]]:
        """只把附件名称交给模型，返回每个名称命中的独立目标事项。"""
        unique_names = list(dict.fromkeys(name.strip() for name in filenames if name.strip()))
        if not unique_names:
            return {}
        check = self.check()
        prompt = (
            "请对附件文件名和目标事项名称进行中文语义模糊匹配。允许文件名包含日期、版本号、回复、更新、"
            "确认、审核、序号和扩展名，也允许同义表达；不能仅因都属于同一专业就判定匹配。"
            "每个目标事项独立，一个附件可以匹配多个目标，但只返回有明确对应关系的结果。"
            "不得读取或推断附件内容。只输出 JSON："
            '{"matches":[{"filename":"原文件名","target":"目标事项原文","confidence":0.0,"reason":"简短依据"}]}。\n'
            f"目标事项：{json.dumps(targets, ensure_ascii=False)}\n"
            f"附件文件名：{json.dumps(unique_names, ensure_ascii=False)}"
        )
        payload = {
            "model": check["resolved_model"],
            "temperature": 0,
            "max_tokens": self.settings.max_tokens,
            "messages": [
                {"role": "system", "content": "你是谨慎的中文文件名匹配器，只输出符合要求的 JSON。"},
                {"role": "user", "content": prompt},
            ],
        }
        response = self._request(f"{self.settings.base_url}/chat/completions", payload)
        content = str(response["choices"][0]["message"].get("content", ""))
        parsed = parse_json_response(content)
        allowed_names = set(unique_names)
        allowed_targets = set(targets)
        result: dict[str, list[dict[str, Any]]] = {}
        for item in parsed.get("matches", []):
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", ""))
            target = str(item.get("target", ""))
            if filename not in allowed_names or target not in allowed_targets:
                continue
            try:
                confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < 0.55:
                continue
            result.setdefault(filename, []).append(
                {"target": target, "confidence": confidence, "reason": str(item.get("reason", ""))}
            )
        return result

    def _request(self, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


def build_prompt(conversations: list[dict[str, Any]], settings: AISettings) -> str:
    compact = []
    current_size = 2
    for conversation in conversations:
        messages = []
        for record in conversation["messages"]:
            item = {
                "record_id": record.get("record_id"),
                "sent_at": record.get("sent_at"),
                "from": record.get("from"),
                "to": record.get("to"),
                "cc": record.get("cc"),
                "subject": record.get("subject"),
                "body": str(record.get("body_text", ""))[: settings.max_body_chars_per_message],
                "attachments": [item.get("filename") for item in record.get("attachments", [])],
            }
            encoded_size = len(json.dumps(item, ensure_ascii=False))
            if current_size + encoded_size > settings.max_input_chars:
                break
            messages.append(item)
            current_size += encoded_size
        if not messages:
            break
        compact.append({key: value for key, value in conversation.items() if key != "messages"} | {"messages": messages})
    source = json.dumps(compact, ensure_ascii=False)
    schema = {
        "matters": [
            {
                "title": "事项名称",
                "conversation_ids": ["conversation-0001"],
                "participants": ["参与人"],
                "first_at": "ISO时间或空字符串",
                "last_at": "ISO时间或空字符串",
                "status": "当前状态；不确定则写待确认",
                "completed": ["已完成事项"],
                "todos": [{"item": "待办", "owner": "责任人或待确认", "due_date": "日期或待确认"}],
                "risks": ["风险或待确认点"],
                "timeline": [{"at": "时间", "event": "事件", "source_record_ids": ["record_id"]}],
                "summary": "简要总结",
            }
        ]
    }
    return (
        "请将以下邮件会话归纳为一个或多个工作事项。合并语义相同的会话，保留时间顺序。"
        "责任人、截止日期、状态没有明确证据时必须写‘待确认’，不得推断。每个时间线事件必须引用 record_id。"
        "输出必须是单个 JSON 对象，不要 Markdown。结构示例：\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n邮件数据：\n"
        + source
    )


def parse_json_response(value: str) -> dict[str, Any]:
    cleaned = value.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("AI 未返回有效 JSON")
        result = json.loads(cleaned[start : end + 1])
    if not isinstance(result, dict):
        raise RuntimeError("AI 返回值必须是 JSON 对象")
    return result
