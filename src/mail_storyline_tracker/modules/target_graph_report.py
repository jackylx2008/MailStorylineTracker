"""Local, evidence-aware target timeline with human-reviewed links."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_target_graph(result: dict[str, Any], path: Path) -> Path:
    payload = json.dumps(result, ensure_ascii=False).replace("<", "\\u003c").replace("\u2028", "\\u2028")
    warning = ""
    if result.get("incomplete"):
        reason = html.escape(str(result.get("stop_reason") or "扫描尚未完成"))
        warning = f'<div class="warning">部分扫描结果：{reason}</div>'
    document = _TEMPLATE.replace("__REPORT_DATA__", payload).replace("__WARNING__", warning)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    return path


_TEMPLATE = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>附件往来沟通链路</title><style>
:root{--ink:#203149;--sub:#5b6c80;--line:#477091;--bg:#f3f6fa;--border:#ccd8e4;--green:#2a9169}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}
header{padding:22px 30px;background:#173651;color:#fff}h1{font-size:24px;margin:0}header p{margin:4px 0 0;color:#d9e6f3}
.warning{margin:12px 24px;padding:12px;background:#fff0d6;border:1px solid #dca34f;border-radius:8px}
.layout{display:grid;grid-template-columns:290px minmax(0,1fr);min-height:calc(100vh - 100px)}
aside{background:#fff;border-right:1px solid var(--border);padding:16px;min-width:0}aside h2{font-size:16px;margin:0 0 10px}input{width:100%;padding:9px;border:1px solid var(--border);border-radius:7px;font:inherit}
.target-list{max-height:calc(100vh - 190px);overflow:auto;margin-top:10px}.target-choice{display:block;width:100%;padding:11px 9px;margin:4px 0;border:1px solid transparent;border-radius:7px;background:#fff;text-align:left;overflow-wrap:anywhere;color:var(--ink)}.target-choice:hover,.target-choice.active{background:#eaf3fa;border-color:#94b8d2}.target-choice small{display:block;color:var(--sub)}
main{min-width:0;padding:18px 22px 60px}main h2{font-size:21px;margin:0 0 8px;overflow-wrap:anywhere}.hint,.meta{color:var(--sub);margin:0 0 11px}.summary{padding:12px 14px;background:#fff;border:1px solid var(--border);border-radius:9px;margin:12px 0}
h3{font-size:16px;margin:22px 0 8px}.graph-scroll{overflow-x:auto;border:1px solid var(--border);border-radius:10px;background:#fff;scrollbar-color:#9cb3c7 #edf2f7}.graph{height:430px;position:relative}.links{position:absolute;inset:0;pointer-events:none}.link{fill:none;stroke:var(--line);stroke-width:2.5}.link.inferred{stroke-dasharray:8 6}.link.approved{stroke:var(--green);stroke-width:3.5}.link.rejected{display:none}
.node{position:absolute;width:210px;transform:translateX(-50%)}.dot{position:absolute;left:50%;width:27px;height:27px;transform:translate(-50%,-50%);border:3px solid #38536a;border-radius:50%;background:#a8d9f3}.node.result .dot{background:#67d2a7}.node.confirmed .dot{border-color:var(--green)}.node-card{margin-top:20px;padding:10px;background:#fff;border:1px solid var(--border);border-radius:8px;box-shadow:0 2px 9px #17365120;min-height:122px}.node.confirmed .node-card{border-color:#64b696;background:#f0faf5}.node time{display:block;font-size:12px;color:#395a72}.node b{font-size:11px;color:var(--green)}.event-link{display:block;color:#185e96;text-decoration:underline;cursor:pointer;overflow-wrap:anywhere}.node p{margin:5px 0 0;font-size:12px;color:var(--sub);display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.edge-button{position:absolute;transform:translateX(-50%);padding:5px 7px;border:1px solid #b88f50;border-radius:6px;background:#fff4db;color:#70450f;cursor:pointer;white-space:nowrap;font-size:12px}.edge-button.approved{border-color:#61aa88;background:#ebf9f1;color:#196144}.edge-button.rejected{border-color:#c3cbd3;background:#f4f6f8;color:#5d6976}.edge-button:hover{filter:brightness(.95)}
.legend{margin:10px 0;color:var(--sub);font-size:12px}.related{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px}.related button{padding:10px;text-align:left;background:#fff;border:1px solid var(--border);border-radius:7px;color:#195889;cursor:pointer}.related small{display:block;color:var(--sub)}
dialog{width:min(900px,calc(100vw - 24px));max-height:calc(100vh - 28px);padding:0;border:1px solid #adbecd;border-radius:11px;box-shadow:0 18px 55px #12263e6a}dialog::backdrop{background:#132a40a8}.dialog-head{position:sticky;top:0;background:#e8f1f8;padding:13px 18px;display:flex;gap:12px;align-items:center;border-bottom:1px solid var(--border)}.dialog-head h2{flex:1;margin:0;font-size:18px}.dialog-body{padding:16px 18px;overflow:auto;max-height:calc(100vh - 145px)}.mail-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px}.mail{border:1px solid var(--border);border-radius:8px;padding:12px;min-width:0}.mail dl{display:grid;grid-template-columns:65px minmax(0,1fr);gap:4px 8px}.mail dt{color:var(--sub)}.mail dd{margin:0;overflow-wrap:anywhere}.mail pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 inherit;background:#f5f7f9;border:1px solid #e0e7ed;border-radius:6px;padding:10px}.actions{position:sticky;bottom:0;padding:12px 18px;background:#fff;border-top:1px solid var(--border);display:flex;gap:10px;align-items:center}.actions button,.close{padding:8px 14px;border:1px solid var(--border);border-radius:7px;background:#fff;cursor:pointer;font:inherit}.actions .yes{background:#e5f7eb;border-color:#64ad7e}.actions .no{background:#fff0ed;border-color:#d4988c}.message{color:#9c3528}
@media(max-width:750px){.layout{display:block}aside{border-right:0;border-bottom:1px solid var(--border)}.target-list{max-height:180px}main{padding:16px}}
</style></head><body>
<header><h1>附件往来沟通链路</h1><p id="subtitle"></p></header>__WARNING__
<div class="layout"><aside><h2>最终文件关键词</h2><input id="search" type="search" placeholder="筛选当前追溯关键词"><div class="target-list" id="target-list"></div></aside>
<main><h2 id="title"></h2><p class="hint">从目标附件邮件倒推；如其后有明确确认回复，则以该回复为结果。每封邮件一个节点。只有点击“有关”审核的连线才进入已确认链路。</p><div id="content"></div></main></div>
<dialog id="dialog"><div class="dialog-head"><h2 id="dialog-title"></h2><button class="close" id="close" type="button">关闭</button></div><div class="dialog-body" id="dialog-body"></div><div class="actions" id="actions"></div></dialog>
<script>
const data=__REPORT_DATA__, list=document.getElementById('target-list'), content=document.getElementById('content');
const dialog=document.getElementById('dialog'), body=document.getElementById('dialog-body'), actions=document.getElementById('actions');
const svgNS='http://www.w3.org/2000/svg';let selected=0;
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=String(text);return n;};
document.getElementById('subtitle').textContent=`${data.targets.length} 个独立事项 · ${data.matched_messages} 封关联邮件 · 生成于 ${data.generated_at||''}`;
function addDetail(dl,label,value){dl.append(el('dt','',label),el('dd','',value||'—'));}
function mailCard(event){const box=el('section','mail');box.append(el('h3','',event.subject||'（无主题）'));const dl=el('dl');
  [['日期',event.sent_at],['发件人',event.from],['收件人',event.to],['Cc',event.cc],['动作',event.action],['附件',(event.all_attachments||[]).join('、')],['来源',`${event.mailbox||''} · UID ${event.uid||''}`],['原始邮件',event.eml_path]].forEach(([a,b])=>addDetail(dl,a,b));
  box.append(dl,el('h4','','邮件正文'),el('pre','',event.body_text||'（无正文）'));return box;}
function showEvent(event){document.getElementById('dialog-title').textContent='完整邮件';body.replaceChildren(mailCard(event));actions.replaceChildren();dialog.showModal();}
function chainIds(topic){const ids=new Set(topic.result_record_id?[topic.result_record_id]:[]);let changed=true;while(changed){changed=false;for(const e of topic.edges||[]){if(e.decision==='approved'&&ids.has(e.to_record_id)&&!ids.has(e.from_record_id)){ids.add(e.from_record_id);changed=true;}}}return ids;}
function showEdge(topic,edge){const map=new Map(topic.events.map(e=>[e.record_id,e]));document.getElementById('dialog-title').textContent='人工确认邮件关联';body.replaceChildren(el('p','meta',edge.reason));const grid=el('div','mail-grid');grid.append(mailCard(map.get(edge.from_record_id)),mailCard(map.get(edge.to_record_id)));body.append(grid);actions.replaceChildren();
  const msg=el('span','message','');const yes=el('button','yes','有关'),no=el('button','no','无关');actions.append(yes,no,msg);
  async function save(decision){yes.disabled=no.disabled=true;msg.textContent='正在保存…';try{if(location.protocol==='file:')throw Error('请从 GUI 的“打开沟通链路页面”进入，才能保存人工确认。');
    const url=`/event-link${location.search}`;const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target:topic.target,from_record_id:edge.from_record_id,to_record_id:edge.to_record_id,decision})});const value=await response.json();if(!response.ok)throw Error(value.error||'保存失败');edge.decision=decision;dialog.close();renderTopic();if(value.report_error)content.prepend(el('div','warning','审核决定已保存，但报告重建失败；请稍后重新生成报告。'));}catch(error){msg.textContent=error.message;yes.disabled=no.disabled=false;}}
  yes.onclick=()=>save('approved');no.onclick=()=>save('rejected');dialog.showModal();}
function renderGraph(topic,ids){const all=topic.events||[],resultIndex=all.findIndex(e=>e.record_id===topic.result_record_id),events=resultIndex>=0?all.slice(0,resultIndex+1):all,scroll=el('div','graph-scroll');const graph=el('div','graph'),width=Math.max(720,events.length*250+110);graph.style.width=`${width}px`;
  const svg=document.createElementNS(svgNS,'svg');svg.setAttribute('class','links');svg.setAttribute('width',width);svg.setAttribute('height',430);svg.setAttribute('aria-hidden','true');graph.append(svg);
  const positions=new Map(events.map((e,i)=>[e.record_id,{x:125+i*250,y:95+(i%2)*20}]));
  for(const edge of topic.edges||[]){const a=positions.get(edge.from_record_id),b=positions.get(edge.to_record_id);if(!a||!b)continue;
    const path=document.createElementNS(svgNS,'path');path.setAttribute('class',`link ${edge.evidence==='reply'?'reply':'inferred'} ${edge.decision}`);
    path.setAttribute('d',`M ${a.x+14} ${a.y} C ${a.x+(b.x-a.x)*.38} ${a.y-45}, ${b.x-(b.x-a.x)*.38} ${b.y-45}, ${b.x-14} ${b.y}`);svg.append(path);
    const label=edge.decision==='approved'?'已确认有关':edge.decision==='rejected'?'已判无关':edge.evidence==='reply'?'回复证据 · 待审核':'需人工确认';
    const button=el('button',`edge-button ${edge.decision}`,label);button.type='button';button.style.left=`${(a.x+b.x)/2}px`;button.style.top=`${Math.max(a.y,b.y)+143}px`;button.onclick=()=>showEdge(topic,edge);graph.append(button);
  }
  for(const event of events){const p=positions.get(event.record_id),node=el('div',`node${event.record_id===topic.result_record_id?' result':''}${ids.has(event.record_id)?' confirmed':''}`);node.style.left=`${p.x}px`;node.style.top=`${p.y}px`;node.append(el('span','dot'));const card=el('div','node-card');card.append(el('time','',event.sent_at||'日期待确认'));
    if(event.record_id===topic.result_record_id)card.append(el('b','',topic.result_is_confirmation?'确认回复 · 结果':'目标文件 · 结果'));else if((topic.seed_record_ids||[]).includes(event.record_id))card.append(el('b','','目标文件命中'));
    const link=el('a','event-link',`${event.action||'沟通'} · ${event.subject||'（无主题）'}`);link.href='#dialog';link.onclick=e=>{e.preventDefault();showEvent(event);};card.append(link,el('p','',`发给：${event.to||'未标明'}`),el('p','',`讨论：${event.discussion||'见完整邮件'}`));if(event.record_id===topic.result_record_id&&topic.result_is_confirmation)card.append(el('p','',`如何确认：收件方明确回复；点击查看原文`));node.append(card);graph.append(node);}
  scroll.append(graph);requestAnimationFrame(()=>{scroll.scrollLeft=scroll.scrollWidth;});return scroll;}
function renderTopic(){const topic=data.targets[selected];if(!topic)return;document.getElementById('title').textContent=topic.target;content.replaceChildren();const ids=chainIds(topic);
  const summary=el('div','summary');if(!topic.anchor_record_id)summary.textContent='本地已审核邮件中尚未找到这个目标文件的命中邮件，暂不能启动追溯。';else summary.textContent=`目标文件命中 ${topic.seed_record_ids.length} 封；候选邮件 ${topic.events.length} 封；已确认链路 ${ids.size} 个节点。${topic.result_is_confirmation?'结果定位到明确确认回复。':'尚无明确确认回复，以最后一封目标文件邮件为当前结果。'}`;content.append(summary);
  if(!topic.events.length)return;content.append(el('h3','','结果向左倒推 · 候选关系'),renderGraph(topic,ids));
  content.append(el('p','legend','绿色边/节点：人工确认有关 · 深色实线：明确回复但尚未人工确认 · 虚线：推断关系，需人工确认。灰色“无关”关系不会进入链路。'));
  const unlinked=topic.events.filter(e=>!ids.has(e.record_id));content.append(el('h3','',`相关但未接入主链（${unlinked.length}）`));const related=el('div','related');for(const event of unlinked){const button=el('button','',`${(event.sent_at||'').slice(0,10)} · ${event.subject||'（无主题）'}`);button.type='button';button.append(el('small','',event.action||''));button.onclick=()=>showEvent(event);related.append(button);}if(!unlinked.length)related.append(el('p','meta','当前候选邮件均已接入链路。'));content.append(related);}
function remembered(){try{return sessionStorage.getItem('storyline-target');}catch(_error){return null;}}
function renderList(){list.replaceChildren();const term=document.getElementById('search').value.trim().toLowerCase();data.targets.forEach((topic,i)=>{if(term&&!topic.target.toLowerCase().includes(term))return;const button=el('button',`target-choice${i===selected?' active':''}`,topic.target);button.type='button';button.append(el('small','',`${(topic.events||[]).length} 封候选邮件`));button.onclick=()=>{selected=i;try{sessionStorage.setItem('storyline-target',topic.target);}catch(_error){}renderList();renderTopic();};list.append(button);});}
const savedIndex=data.targets.findIndex(topic=>topic.target===remembered());selected=savedIndex>=0?savedIndex:Math.max(0,data.targets.findIndex(topic=>topic.events?.length));
renderList();renderTopic();document.getElementById('search').oninput=renderList;document.getElementById('close').onclick=()=>dialog.close();dialog.onclick=e=>{if(e.target===dialog)dialog.close();};
</script></body></html>'''
