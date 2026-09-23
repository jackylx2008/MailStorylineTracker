from __future__ import annotations

import html
from pathlib import Path
from typing import Any


STYLE = """
:root{color-scheme:light;--ink:#172033;--muted:#637083;--line:#dce3ec;--accent:#2857c5;--bg:#f4f7fb;--card:#fff;--risk:#a63a29}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}
header{background:#15284b;color:white;padding:28px max(24px,6vw)}header h1{margin:0 0 6px;font-size:25px}header p{margin:0;color:#ccd8ee}
main{max-width:1200px;margin:24px auto;padding:0 20px}.toolbar,.card{background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:0 5px 18px #23395d10}
.toolbar{padding:14px;margin-bottom:18px;position:sticky;top:8px;z-index:2}input{width:100%;padding:10px 12px;border:1px solid #b8c3d3;border-radius:8px;font-size:15px}
.card{padding:20px;margin:14px 0}.meta{color:var(--muted);font-size:13px}.status{display:inline-block;padding:2px 9px;background:#e8eefc;color:#244ba6;border-radius:999px}
h2{margin:0 0 8px;font-size:20px}h3{font-size:15px;margin:16px 0 5px}.timeline{border-left:3px solid #aebfe8;padding-left:18px}.event{margin:10px 0}.risk{color:var(--risk)}code{font-size:12px}details{margin-top:10px}
"""


def write_mail_review(records: list[dict[str, Any]], path: Path) -> Path:
    cards = []
    for record in sorted(records, key=lambda item: item.get("sent_at", ""), reverse=True):
        body = html.escape(str(record.get("body_text", ""))[:3000])
        attachments = "、".join(html.escape(str(item.get("filename", ""))) for item in record.get("attachments", [])) or "无"
        cards.append(
            f'''<article class="card searchable"><h2>{html.escape(str(record.get("subject") or "（无主题）"))}</h2>
            <div class="meta">{html.escape(str(record.get("sent_at", "")))} · {html.escape(str(record.get("from", "")))} → {html.escape(str(record.get("to", "")))}</div>
            <p>命中：{html.escape("、".join(record.get("matched_by", [])))}</p><p>附件：{attachments}</p>
            <details><summary>正文摘录与来源</summary><pre>{body}</pre><code>{html.escape(str(record.get("eml_path", "")))}</code></details></article>'''
        )
    return _write_page(path, "邮件下载审核", f"共存档 {len(records)} 封匹配邮件", "".join(cards))


def write_storyline_report(result: dict[str, Any], path: Path) -> Path:
    cards = []
    for matter in result.get("matters", []):
        completed = _list(matter.get("completed", []))
        risks = _list(matter.get("risks", []), "risk")
        todos = "".join(
            f"<li>{html.escape(str(item.get('item', '')))} — {html.escape(str(item.get('owner', '待确认')))}，{html.escape(str(item.get('due_date', '待确认')))}</li>"
            for item in matter.get("todos", []) if isinstance(item, dict)
        ) or "<li>无明确待办</li>"
        events = "".join(
            f'''<div class="event"><strong>{html.escape(str(item.get("at", "")))}</strong> — {html.escape(str(item.get("event", "")))}
            <div class="meta">来源：{html.escape(", ".join(str(value) for value in item.get("source_record_ids", [])))}</div></div>'''
            for item in matter.get("timeline", []) if isinstance(item, dict)
        )
        cards.append(
            f'''<article class="card searchable"><h2>{html.escape(str(matter.get("title", "未命名事项")))}</h2>
            <div class="meta">{html.escape(str(matter.get("first_at", "")))} — {html.escape(str(matter.get("last_at", "")))}</div>
            <p><span class="status">{html.escape(str(matter.get("status", "待确认")))}</span></p>
            <p>{html.escape(str(matter.get("summary", "")))}</p><h3>参与人</h3>{_list(matter.get("participants", []))}
            <h3>已完成</h3>{completed}<h3>待办 / 责任人 / 截止日期</h3><ul>{todos}</ul>
            <h3>风险</h3>{risks}<h3>时间线</h3><div class="timeline">{events or "无时间线"}</div></article>'''
        )
    return _write_page(path, "工作事项时间线", f"模型：{result.get('model', '')} · 事项数：{len(result.get('matters', []))}", "".join(cards))


def _list(values: Any, css_class: str = "") -> str:
    items = values if isinstance(values, list) else []
    content = "".join(f"<li>{html.escape(str(value))}</li>" for value in items) or "<li>无</li>"
    return f'<ul class="{css_class}">{content}</ul>'


def _write_page(path: Path, title: str, subtitle: str, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>{html.escape(title)}</title><style>{STYLE}</style></head><body><header><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></header>
    <main><div class="toolbar"><input id="q" placeholder="搜索标题、参与人、正文或状态"></div>{body or '<div class="card">暂无数据</div>'}</main>
    <script>const q=document.querySelector('#q');q.addEventListener('input',()=>{{const v=q.value.toLowerCase();document.querySelectorAll('.searchable').forEach(x=>x.hidden=!x.innerText.toLowerCase().includes(v));}});</script>
    </body></html>'''
    path.write_text(document, encoding="utf-8")
    return path
