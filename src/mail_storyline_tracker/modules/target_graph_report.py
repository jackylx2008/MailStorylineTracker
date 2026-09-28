"""离线目标事项节点图；页面脚本只使用内嵌的本地报告数据。"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_target_graph(result: dict[str, Any], path: Path) -> Path:
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c")
    warning = ""
    if result.get("incomplete"):
        reason = html.escape(str(result.get("stop_reason") or "扫描尚未完成"))
        warning = (
            '<div class="warning" role="alert"><strong>部分扫描结果</strong>'
            f'<span>{reason}。重新运行后会从已保存的 UID 状态继续。</span></div>'
        )
    document = _TEMPLATE.replace("__REPORT_DATA__", payload).replace("__WARNING__", warning)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


_TEMPLATE = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>附件往来沟通链路</title><style>
:root{color-scheme:light;--bg:#f5f7fa;--surface:#fff;--ink:#172033;--muted:#637083;--line:#44546a;--blue:#a9dcf4;--green:#61d2ac;--purple:#b39be5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}
header{background:#183558;color:#fff;padding:22px max(18px,4vw)}h1{margin:0;font-size:24px}header p{margin:5px 0 0;color:#d8e7f7}
.toolbar{position:sticky;top:0;z-index:5;display:flex;gap:8px;flex-wrap:wrap;padding:11px max(18px,4vw);background:#ffffffed;border-bottom:1px solid #d6e0eb}
input{flex:1;min-width:220px;padding:9px 11px;border:1px solid #b6c4d4;border-radius:7px;font:inherit}
button{font:inherit;cursor:pointer}.tool-button{padding:8px 12px;border:1px solid #b6c4d4;border-radius:7px;background:#fff;color:var(--ink)}
main{max-width:1500px;margin:18px auto;padding:0 18px 50px}.hint{margin:0 0 14px;color:var(--muted)}
.warning{max-width:1500px;margin:15px auto 0;padding:11px 16px;border:1px solid #e7b467;border-radius:8px;background:#fff5df;color:#75450f;display:flex;gap:10px;flex-wrap:wrap}
.topic{margin:0 0 16px;border:1px solid #d7e0e9;border-radius:12px;background:var(--surface);box-shadow:0 3px 14px #203a5310;overflow:hidden}
.topic summary{display:flex;align-items:center;gap:12px;padding:15px 18px;cursor:pointer;font-size:17px;font-weight:600;list-style:none}
.topic summary::-webkit-details-marker{display:none}.topic summary:before{content:'▸';color:#245b94}.topic[open] summary:before{content:'▾'}
.count{margin-left:auto;color:var(--muted);font-size:12px;font-weight:400}.graph-scroll{overflow-x:auto;overflow-y:hidden;border-top:1px solid #e4eaf1;background:#fff;scrollbar-color:#9caec0 #eef2f6}
.graph{position:relative;height:570px}.links{position:absolute;inset:0;overflow:visible}.link{fill:none;stroke:var(--line);stroke-width:2.5;stroke-linecap:round}.link.sequence{stroke-dasharray:6 5;opacity:.65}
.node{position:absolute;width:230px;transform:translateX(-50%)}.dot{position:absolute;left:50%;top:0;width:34px;height:34px;transform:translate(-50%,-50%);border:3px solid #374452;border-radius:50%;background:var(--blue);box-shadow:0 0 0 4px #fff}
.node.branch .dot{background:var(--purple)}.node.result .dot{background:var(--green)}.node-card{margin-top:24px;padding:10px 12px;border:1px solid #cfd9e3;border-radius:8px;background:#fff;box-shadow:0 3px 9px #17203317;min-height:94px}
.node.result .node-card{border-color:#57ae8a;background:#f0fbf5}.node-date{display:block;color:#315270;font-size:12px;font-weight:600}.node-label{display:block;margin-top:2px;color:#287355;font-size:11px;font-weight:700}
.event-link{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;max-height:42px;margin-top:4px;color:#164d89;text-decoration:underline;text-underline-offset:2px;overflow-wrap:anywhere}
.event-link:hover,.event-link:focus-visible{color:#0b75bd}.empty{padding:18px;color:var(--muted)}.legend{display:flex;gap:18px;flex-wrap:wrap;padding:0 18px 15px;color:var(--muted);font-size:12px}.swatch{display:inline-block;width:11px;height:11px;margin-right:5px;border:1px solid #44546a;border-radius:50%;vertical-align:middle}.swatch.result{background:var(--green)}.swatch.earlier{background:var(--blue)}.swatch.branch{background:var(--purple)}
dialog{width:min(760px,calc(100vw - 24px));max-height:calc(100vh - 28px);padding:0;border:1px solid #b6c8da;border-radius:12px;box-shadow:0 22px 60px #091c3970}dialog::backdrop{background:#0e2039a8}
.dialog-head{position:sticky;top:0;display:flex;align-items:flex-start;gap:12px;padding:16px 20px;background:#eaf2f9;border-bottom:1px solid #cbd7e4;z-index:1}.dialog-head h2{flex:1;margin:0;font-size:18px}.dialog-body{padding:18px 20px;overflow:auto;max-height:calc(100vh - 105px)}.dialog-body dl{display:grid;grid-template-columns:78px minmax(0,1fr);gap:6px 12px;margin:0 0 18px}.dialog-body dt{color:var(--muted)}.dialog-body dd{margin:0;overflow-wrap:anywhere}.dialog-body h3{font-size:14px;margin:18px 0 8px}.mail-body{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;border:1px solid #e0e6ed;border-radius:8px;padding:14px;max-height:none}
[hidden]{display:none!important}@media(max-width:600px){.count{display:none}.node{width:205px}.topic summary{font-size:15px}}
</style></head><body>
<header><h1>附件往来沟通链路</h1><p id="subtitle"></p></header>__WARNING__
<div class="toolbar"><input id="search" type="search" placeholder="搜索事项、日期、主题、参与人或附件" aria-label="搜索事项和邮件"><button class="tool-button" id="expand" type="button">展开全部</button><button class="tool-button" id="collapse" type="button">折叠全部</button></div>
<main><p class="hint">右侧绿色节点是当前结果；沿曲线向左回溯往来记录。点击节点简介查看完整邮件内容。实线表示邮件回复关系，虚线表示同一会话内的时间顺序。</p><section id="topics" aria-live="polite"></section></main>
<dialog id="event-dialog" aria-labelledby="dialog-title"><div class="dialog-head"><h2 id="dialog-title"></h2><button class="tool-button" id="dialog-close" type="button" aria-label="关闭">关闭</button></div><div class="dialog-body" id="dialog-body"></div></dialog>
<script>
const data=__REPORT_DATA__;
const topics=document.getElementById('topics');
const dialog=document.getElementById('event-dialog');
const svgNS='http://www.w3.org/2000/svg';
const el=(tag,className,text)=>{const item=document.createElement(tag);if(className)item.className=className;if(text!==undefined)item.textContent=String(text);return item;};
document.getElementById('subtitle').textContent=`${data.targets.length} 个独立事项 · ${data.matched_messages} 封关联邮件 · 生成于 ${data.generated_at||''}`;
function addDetail(list,label,value){list.append(el('dt','',label),el('dd','',value||'—'));}
function showEvent(event){
  document.getElementById('dialog-title').textContent=event.subject||'（无主题）';
  const body=document.getElementById('dialog-body');body.replaceChildren();
  const list=el('dl');
  addDetail(list,'日期',event.sent_at);addDetail(list,'动作',event.action);
  addDetail(list,'发件人',event.from);addDetail(list,'收件人',event.to);addDetail(list,'Cc',event.cc);
  addDetail(list,'附件',(event.all_attachments||event.attachments||[]).join('、'));
  addDetail(list,'匹配原因',(event.match_reasons||[]).join('、'));
  addDetail(list,'来源',`${event.mailbox||''} · UID ${event.uid||''} · ${event.record_id||''}`);
  addDetail(list,'原始邮件',event.eml_path);
  body.append(list,el('h3','','邮件正文'),el('div','mail-body',event.body_text||'（无正文）'));
  dialog.showModal();
}
function graphFor(topic){
  const events=topic.events||[];
  if(!events.length)return el('div','empty','尚未发现关联邮件');
  const scroll=el('div','graph-scroll');
  const graph=el('div','graph');const width=Math.max(780,190+events.length*260);graph.style.width=`${width}px`;
  const svg=document.createElementNS(svgNS,'svg');svg.setAttribute('class','links');svg.setAttribute('width',width);svg.setAttribute('height',570);svg.setAttribute('viewBox',`0 0 ${width} 570`);svg.setAttribute('aria-hidden','true');graph.append(svg);
  const index=new Map(events.map((event,i)=>[event.record_id,i]));
  const points=events.map((event,i)=>{
    const parent=index.get(event.parent_record_id);
    const branch=parent!==undefined&&parent<i-1&&i!==events.length-1;
    return {x:130+i*260,y:branch?(i%2?100:390):250,branch};
  });
  events.forEach((event,i)=>{
    const parent=index.get(event.parent_record_id);if(parent===undefined||parent>=i)return;
    const a=points[parent],b=points[i],gap=b.x-a.x;
    const path=document.createElementNS(svgNS,'path');
    path.setAttribute('class',`link ${event.link_type==='sequence'?'sequence':'reply'}`);
    const bend=a.y===b.y?-22:0;
    path.setAttribute('d',`M ${a.x+17} ${a.y} C ${a.x+gap*.38} ${a.y+bend}, ${b.x-gap*.38} ${b.y+bend}, ${b.x-17} ${b.y}`);
    svg.append(path);
  });
  events.forEach((event,i)=>{
    const point=points[i],latest=i===events.length-1;
    const node=el('div',`node${latest?' result':''}${point.branch?' branch':''}`);
    node.style.left=`${point.x}px`;node.style.top=`${point.y}px`;
    node.append(el('span','dot'));
    const card=el('div','node-card');
    const date=el('time','node-date',(event.sent_at||'日期待确认').slice(0,10));
    if(event.sent_at)date.dateTime=event.sent_at;
    card.append(date);
    if(latest)card.append(el('span','node-label','当前结果'));
    const link=el('a','event-link',`${event.action||'往来沟通'} · ${event.subject||'（无主题）'}`);
    link.href='#event-dialog';link.title='查看完整邮件内容';
    link.addEventListener('click',click=>{click.preventDefault();showEvent(event);});
    card.append(link);node.append(card);graph.append(node);
  });
  scroll.append(graph);
  requestAnimationFrame(()=>{if(scroll.isConnected)scroll.scrollLeft=scroll.scrollWidth;});
  return scroll;
}
function render(){
  topics.replaceChildren();
  const firstWithEvents=(data.targets||[]).findIndex(topic=>(topic.events||[]).length>0);
  (data.targets||[]).forEach((topic,i)=>{
    const section=el('details','topic');section.open=i===(firstWithEvents<0?0:firstWithEvents);
    const summary=el('summary','',topic.target);
    summary.append(el('span','count',`${(topic.events||[]).length} 个事件 · ${(topic.attachment_names||[]).length} 个附件名`));
    section.append(summary,graphFor(topic));
    if((topic.events||[]).length){
      const legend=el('div','legend');
      [['result','当前结果'],['earlier','往来事件'],['branch','分支事件']].forEach(([kind,label])=>{
        const item=el('span');item.append(el('i',`swatch ${kind}`),document.createTextNode(label));legend.append(item);
      });
      section.append(legend);
    }
    section.addEventListener('toggle',()=>{if(section.open){const scroll=section.querySelector('.graph-scroll');if(scroll)scroll.scrollLeft=scroll.scrollWidth;}});
    topics.append(section);
  });
}
render();
document.getElementById('search').addEventListener('input',event=>{
  const needle=event.target.value.trim().toLowerCase();
  [...topics.children].forEach((section,i)=>{section.hidden=!!needle&&!JSON.stringify(data.targets[i]).toLowerCase().includes(needle);if(needle&&!section.hidden)section.open=true;});
});
document.getElementById('expand').addEventListener('click',()=>topics.querySelectorAll('.topic:not([hidden])').forEach(section=>section.open=true));
document.getElementById('collapse').addEventListener('click',()=>topics.querySelectorAll('.topic').forEach(section=>section.open=false));
document.getElementById('dialog-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
</script></body></html>'''
