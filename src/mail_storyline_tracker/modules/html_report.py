from __future__ import annotations

import html
import json
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


def write_target_mindmap(result: dict[str, Any], path: Path) -> Path:
    """生成单文件、离线可搜索的事项沟通链路与时间线。"""
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    path.parent.mkdir(parents=True, exist_ok=True)
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>附件往来沟通链路</title><style>
:root{{--bg:#f3f6fa;--surface:#fff;--ink:#172033;--muted:#667085;--line:#b8c5d8;--primary:#1f4f99;--soft:#eaf1fb;--accent:#bf6b21}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}}
header{{background:linear-gradient(120deg,#10284d,#245c98);color:#fff;padding:26px max(20px,5vw)}}h1{{margin:0;font-size:24px;font-weight:500}}header p{{margin:5px 0 0;color:#d9e4f4}}
.toolbar{{position:sticky;top:0;z-index:5;display:flex;gap:8px;flex-wrap:wrap;padding:12px max(16px,4vw);background:#ffffffee;border-bottom:1px solid #d5deea;backdrop-filter:blur(8px)}}
input{{flex:1;min-width:240px;padding:9px 11px;border:1px solid #aebbd0;border-radius:7px;font:inherit}}button{{padding:8px 12px;border:1px solid #aebbd0;border-radius:7px;background:#fff;color:var(--ink);font:inherit}}
main{{max-width:1380px;margin:22px auto;padding:0 18px 50px}}.root{{width:max-content;max-width:90%;margin:0 auto 24px;padding:13px 22px;border-radius:10px;background:var(--primary);color:#fff;text-align:center}}
.topics{{position:relative}}.topics:before{{content:"";position:absolute;left:24px;top:0;bottom:0;width:2px;background:var(--line)}}
details{{position:relative;margin:0 0 16px 54px;background:var(--surface);border:1px solid #d8e0eb;border-radius:10px;box-shadow:0 4px 14px #243b5a12}}
details:before{{content:"";position:absolute;left:-30px;top:25px;width:30px;height:2px;background:var(--line)}}summary{{padding:14px 16px;font-size:16px;font-weight:500;list-style:none;display:flex;align-items:center;gap:10px}}summary::-webkit-details-marker{{display:none}}
.count{{margin-left:auto;color:var(--muted);font-size:12px;font-weight:400}}.empty{{padding:0 18px 18px;color:var(--muted)}}
.chain{{position:relative;padding:6px 18px 20px 42px}}.chain:before{{content:"";position:absolute;left:23px;top:5px;bottom:25px;width:2px;background:#8ca8d0}}
.event{{position:relative;margin:0 0 13px;padding:12px 14px;background:var(--soft);border-radius:8px}}.event:before{{content:"";position:absolute;left:-25px;top:18px;width:11px;height:11px;border-radius:50%;background:var(--primary);box-shadow:0 0 0 4px var(--surface)}}
.event-head{{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}}.time{{color:var(--primary);font-weight:500}}.action{{font-weight:500}}.route,.subject,.attachments,.source{{margin-top:4px}}.route,.source{{color:var(--muted);font-size:12px}}.attachments{{color:var(--accent)}}
.match{{display:inline-block;margin:4px 5px 0 0;padding:1px 7px;border-radius:999px;background:#fff;color:#365b8f;font-size:12px}}[hidden]{{display:none!important}}
@media(max-width:640px){{details{{margin-left:32px}}.topics:before{{left:12px}}details:before{{left:-20px;width:20px}}.chain{{padding-left:32px}}.chain:before{{left:16px}}.event:before{{left:-21px}}}}
</style></head><body><header><h1>附件往来沟通链路</h1><p id="subtitle"></p></header>
<div class="toolbar"><input id="search" type="search" placeholder="搜索事项、主题、参与人或附件"><button id="expand" type="button">展开全部</button><button id="collapse" type="button">折叠全部</button></div>
<main><div class="root">目标附件事项总览</div><section class="topics" id="topics" aria-live="polite"></section></main>
<script>const data={payload};const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const topics=document.getElementById('topics');document.getElementById('subtitle').textContent=`${{data.targets.length}} 个独立事项 · ${{data.matched_messages}} 封关联邮件 · 生成于 ${{data.generated_at}}`;
function render(q=''){{const needle=q.trim().toLowerCase();topics.innerHTML=data.targets.map((topic,i)=>{{const text=JSON.stringify(topic).toLowerCase();const hide=needle&&!text.includes(needle);const events=topic.events.map(e=>`<article class="event"><div class="event-head"><span class="time">${{esc(e.sent_at)}}</span><span class="action">${{esc(e.action)}}</span></div><div class="route">${{esc(e.from)}} → ${{esc(e.to)}}${{e.cc?' · Cc '+esc(e.cc):''}}</div><div class="subject">${{esc(e.subject||'（无主题）')}}</div>${{e.attachments.length?`<div class="attachments">附件：${{e.attachments.map(esc).join('、')}}</div>`:''}}<div>${{e.match_reasons.map(x=>`<span class="match">${{esc(x)}}</span>`).join('')}}</div><div class="source">${{esc(e.mailbox)}} · UID ${{esc(e.uid)}} · ${{esc(e.record_id)}}</div></article>`).join('');return `<details class="topic" ${{i===0?'open':''}} ${{hide?'hidden':''}}><summary>${{esc(topic.target)}}<span class="count">${{topic.events.length}} 个事件 · ${{topic.attachment_names.length}} 个附件名</span></summary>${{events?`<div class="chain">${{events}}</div>`:'<div class="empty">尚未发现关联邮件</div>'}}</details>`;}}).join('')}}
render();document.getElementById('search').addEventListener('input',e=>render(e.target.value));document.getElementById('expand').addEventListener('click',()=>document.querySelectorAll('details:not([hidden])').forEach(x=>x.open=true));document.getElementById('collapse').addEventListener('click',()=>document.querySelectorAll('details').forEach(x=>x.open=false));
</script></body></html>'''
    path.write_text(document, encoding="utf-8")
    return path


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
