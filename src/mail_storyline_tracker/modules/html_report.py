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
        body_text = str(record.get("body_text", ""))
        body = html.escape(body_text[:3000])
        attachments = "、".join(html.escape(str(item.get("filename", ""))) for item in record.get("attachments", [])) or "无"
        email_text = " ".join(
            [str(record.get(name, "")) for name in ("from", "to", "cc")]
            + [str(address) for values in record.get("addresses", {}).values() for address in values]
        )
        keyword_text = " ".join(
            [str(record.get("subject", "")), body_text]
            + [str(item.get("filename", "")) for item in record.get("attachments", [])]
        )
        record_id = html.escape(str(record.get("record_id", "")), quote=True)
        email_index = html.escape(email_text, quote=True)
        keyword_index = html.escape(keyword_text, quote=True)
        cc = f' · Cc: {html.escape(str(record["cc"]))}' if record.get("cc") else ""
        cards.append(
            f'''<article class="card review-item" data-record-id="{record_id}" data-email="{email_index}" data-keywords="{keyword_index}"><h2>{html.escape(str(record.get("subject") or "（无主题）"))}</h2>
            <div class="meta">{html.escape(str(record.get("sent_at", "")))} · {html.escape(str(record.get("from", "")))} → {html.escape(str(record.get("to", "")))}{cc}</div>
            <p>命中：{html.escape("、".join(record.get("matched_by", [])))}</p><p>附件：{attachments}</p>
            <details><summary>正文摘录与来源</summary><pre>{body}</pre><code>{html.escape(str(record.get("eml_path", "")))}</code></details>
            <div class="review-actions"><button type="button" class="delete-review" aria-label="从审核页删除此条目">删除条目</button></div></article>'''
        )
    return _write_review_page(path, len(records), "".join(cards))


REVIEW_STYLE = """
.review-toolbar{display:grid;grid-template-columns:repeat(2,minmax(220px,1fr));gap:12px}
.review-toolbar label{display:block;font-size:13px;color:var(--muted);font-weight:600}
.review-toolbar input{display:block;margin-top:4px}.review-summary{grid-column:1/-1;color:var(--muted);font-size:13px}
.review-actions{display:flex;justify-content:flex-end;margin-top:14px;padding-top:10px;border-top:1px solid var(--line)}
.delete-review,#undo-delete{padding:6px 11px;border:1px solid #b8c3d3;border-radius:7px;background:#fff;color:#9b302b;cursor:pointer;font:inherit}
.delete-review:hover,#undo-delete:hover{background:#fff0ee}#undo-delete{color:var(--ink);margin-left:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}.empty-review{padding:18px;color:var(--muted)}
@media(max-width:640px){.review-toolbar{grid-template-columns:1fr}}
"""


REVIEW_SCRIPT = """
const cards=[...document.querySelectorAll('.review-item')];
const emailFilter=document.getElementById('email-filter');
const keywordFilter=document.getElementById('keyword-filter');
const summary=document.getElementById('review-summary');
const syncStatus=document.getElementById('review-sync-status');
const empty=document.getElementById('empty-review');
const undo=document.getElementById('undo-delete');
const apiUrl=new URLSearchParams(location.search).get('review_api');
const storageKey='mail-storyline-review-deleted-v1:'+location.pathname;
let storageAvailable=true;
let deleted;
try{deleted=new Set(JSON.parse(localStorage.getItem(storageKey)||'[]'));}
catch(error){deleted=new Set();storageAvailable=false;}
let lastDeleted='';
let apiReady=false;
const terms=value=>value.toLocaleLowerCase().split(/[,，;；]+/).map(x=>x.trim()).filter(Boolean);
const matches=(text,values)=>!values.length||values.some(value=>text.toLocaleLowerCase().includes(value));
function saveDeleted(){
  if(!storageAvailable)return;
  try{localStorage.setItem(storageKey,JSON.stringify([...deleted]));}
  catch(error){storageAvailable=false;}
}
function update(){
  const emails=terms(emailFilter.value),keywords=terms(keywordFilter.value);
  let shown=0;
  cards.forEach(card=>{
    const isDeleted=deleted.has(card.dataset.recordId);
    card.hidden=isDeleted||!matches(card.dataset.email||'',emails)||!matches(card.dataset.keywords||'',keywords);
    if(!card.hidden)shown++;
  });
  summary.textContent=`显示 ${shown} / ${cards.length} 封 · 已排除 ${deleted.size} 封`;
  empty.hidden=shown!==0;
  undo.hidden=!lastDeleted||!apiReady;
}
async function sendDecision(action,recordIds){
  const response=await fetch(apiUrl,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,record_ids:recordIds})});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'审核状态保存失败');
  deleted=new Set(result.excluded_record_ids);
  saveDeleted();update();
  return result;
}
document.querySelectorAll('.delete-review').forEach(button=>button.addEventListener('click',async()=>{
  const card=button.closest('.review-item');
  button.disabled=true;
  try{
    const result=await sendDecision('exclude',[card.dataset.recordId]);
    lastDeleted=card.dataset.recordId;
    syncStatus.textContent=result.report_error?'排除已保存，但故事线重建失败；请重新生成报告。':'审核决定已保存到本地项目，后续故事线将跳过该邮件。';
    update();
  }catch(error){syncStatus.textContent=`保存失败：${error.message}`;}
  finally{button.disabled=false;}
}));
undo.addEventListener('click',async()=>{
  undo.disabled=true;
  try{const result=await sendDecision('restore',[lastDeleted]);lastDeleted='';syncStatus.textContent=result.report_error?'恢复已保存，但故事线重建失败；请重新生成报告。':'已恢复审核条目及后续故事线。';update();}
  catch(error){syncStatus.textContent=`恢复失败：${error.message}`;}
  finally{undo.disabled=false;}
});
emailFilter.addEventListener('input',update);
keywordFilter.addEventListener('input',update);
document.querySelectorAll('.delete-review').forEach(button=>button.disabled=true);
update();
if(apiUrl){
  sendDecision('merge',[...deleted]).then(result=>{
    apiReady=true;
    document.querySelectorAll('.delete-review').forEach(button=>button.disabled=false);
    syncStatus.textContent=result.report_error?'审核决定已同步，但故事线重建失败；请重新生成报告。':`审核决定已与本地项目同步，共排除 ${deleted.size} 封邮件。`;
    update();
  }).catch(error=>{syncStatus.textContent=`审核状态同步失败：${error.message}；请从 GUI 重新打开审核页。`;});
}else{syncStatus.textContent='请从项目 GUI 打开审核页，才能将删除决定同步到后续故事线。';}
"""


def _write_review_page(path: Path, count: int, cards: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>邮件下载审核</title><style>{STYLE}{REVIEW_STYLE}</style></head><body>
    <header><h1>邮件下载审核</h1><p>审核清单含 {count} 封邮件</p></header>
    <main><div class="toolbar review-toolbar">
    <label>邮箱筛选（From / To / Cc）<input id="email-filter" type="search" placeholder="输入邮箱地址或片段；多个值用逗号分隔"></label>
    <label>关键词筛选（主题 / 正文 / 附件名）<input id="keyword-filter" type="search" placeholder="输入关键词；多个值用逗号分隔"></label>
    <div class="review-summary"><span id="review-summary"></span><button type="button" id="undo-delete" hidden>撤销上次删除</button><br><span id="review-sync-status" role="status"></span><br>删除条目会写入本地审核排除记录，后续故事线不再包含该邮件；原始邮件、附件和服务器邮件仍保留。</div>
    </div>{cards}<div id="empty-review" class="card empty-review" hidden>没有符合当前筛选条件的邮件。</div></main>
    <script>{REVIEW_SCRIPT}</script></body></html>'''
    path.write_text(document, encoding="utf-8")
    return path


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
    """生成单文件、离线可搜索的节点连线故事线。"""
    from .target_graph_report import write_target_graph

    return write_target_graph(result, path)


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
