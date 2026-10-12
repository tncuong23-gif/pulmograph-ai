(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const SVG = 'http://www.w3.org/2000/svg';
  const state = {mode:'related', result:null, facts:[], selected:-1, positions:new Map(), anchorIds:new Set()};
  const el = (name, cls, value) => { const x=document.createElement(name); if(cls)x.className=cls; if(value!==undefined)x.textContent=String(value); return x; };
  const svg = (name, attrs={}) => { const x=document.createElementNS(SVG,name); Object.entries(attrs).forEach(([k,v])=>x.setAttribute(k,String(v))); return x; };
  const show = (id, yes) => $(id).classList.toggle('hidden',!yes);
  const uniqueFacts = (result) => {
    const list=[...(result.facts||[]),...(result.paths||[]).flatMap(p=>p.facts||[])];
    const seen=new Map();
    for(const f of list){
      const key=`${f.subject.id}\u0000${f.predicate}\u0000${f.object.id}`;
      if(!seen.has(key))seen.set(key,{...f,doc_ids:[...(f.doc_ids||[])],evidence:[...(f.evidence||[])]});
      else {const old=seen.get(key); old.doc_ids=[...new Set([...old.doc_ids,...(f.doc_ids||[])])];
        const keys=new Set(old.evidence.map(e=>`${e.doc_id}/${e.evidence_id}`));
        for(const e of f.evidence||[]){const k=`${e.doc_id}/${e.evidence_id}`; if(!keys.has(k)){old.evidence.push(e);keys.add(k);}}}
    }
    return [...seen.values()];
  };
  function setMode(mode){
    state.mode=mode;
    document.querySelectorAll('.mode').forEach(b=>{b.classList.toggle('active',b.dataset.mode===mode);b.setAttribute('aria-pressed',b.dataset.mode===mode?'true':'false');});
    show('secondField',mode==='path'); show('intentField',mode==='related'); show('chainField',mode==='chain');
    $('target').required=mode==='path';
  }
  document.querySelectorAll('.mode').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
  document.querySelectorAll('[data-example]').forEach(b=>b.addEventListener('click',()=>{
    $('mention').value=b.dataset.example;
    if(b.dataset.target){setMode('path');$('target').value=b.dataset.target;}
    else {setMode('related');$('intent').value=b.dataset.intent;}
    $('queryForm').requestSubmit();
  }));
  fetch('/modules/kg-explorer/api/meta').then(r=>r.json()).then(meta=>{
    const select=$('intent'); for(const i of meta.intents||[]){if(i.id==='related')continue;const opt=el('option',null,`${i.description} (${i.id})`);opt.value=i.id;select.append(opt);}
  }).catch(()=>{});
  fetch('/modules/kg-explorer/api/health').then(r=>{ $('connection').textContent=r.ok?'Neo4j đã kết nối':'Chưa kết nối Neo4j';$('connection').parentElement.classList.toggle('offline',!r.ok); }).catch(()=>{ $('connection').textContent='Chưa kết nối Neo4j';$('connection').parentElement.classList.add('offline'); });
  $('queryForm').addEventListener('submit',async(ev)=>{
    ev.preventDefault();
    const mention=$('mention').value.trim(), target=$('target').value.trim();
    if(!mention || (state.mode==='path'&&!target))return;
    const payload={mentions:state.mode==='path'?[mention,target]:[mention],limit:60};
    if(state.mode==='path'){payload.path=true;payload.max_hops=3;}
    else if(state.mode==='chain')payload.chain=$('chain').value;
    else payload.intents=[$('intent').value];
    $('searchBtn').disabled=true; $('searchBtn').querySelector('span').textContent='Đang truy vấn…';
    $('feedback').textContent='';$('feedback').classList.remove('error');
    try{
      const response=await fetch('/modules/kg-explorer/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const data=await response.json();if(!response.ok)throw new Error(data.error||'Truy vấn thất bại.');
      state.result=data; state.facts=uniqueFacts(data); state.selected=-1;
      render(data,mention,target);
    }catch(error){$('feedback').textContent=error.message;$('feedback').classList.add('error');}
    finally{$('searchBtn').disabled=false;$('searchBtn').querySelector('span').textContent='Khám phá tri thức';}
  });
  function render(result,mention,target){
    const facts=state.facts;
    if(result.status==='no_entity'){$('feedback').textContent='Không tìm thấy thực thể. Hãy thử tên đầy đủ hoặc một tên đồng nghĩa.';}
    else if(result.status==='no_facts'){$('feedback').textContent='Đã tìm thấy thực thể nhưng chưa có quan hệ phù hợp trong đồ thị.';}
    else if(result.notes?.length){$('feedback').textContent=result.notes.join(' · ');}
    show('results',true);
    $('resultCount').textContent=facts.length;
    $('resultSubtitle').textContent=state.mode==='path'?`Đường đi từ “${mention}” đến “${target}”`:`Quan hệ liên quan đến “${mention}”`;
    const nodes=new Map();facts.forEach(f=>{nodes.set(f.subject.id,f.subject);nodes.set(f.object.id,f.object);});
    state.anchorIds=new Set(Object.values(result.anchors||{}).flat().map(a=>a.id));
    for(const anchors of Object.values(result.anchors||{}))for(const a of anchors)nodes.set(a.id,a);
    $('nodeCount').textContent=nodes.size;
    $('edgeCount').textContent=facts.length;
    $('docCount').textContent=new Set(facts.flatMap(f=>f.doc_ids||[])).size;
    $('factsMeta').textContent=`${facts.length} quan hệ · chọn để xem bằng chứng`;
    renderFacts();renderGraph([...nodes.values()],facts);
    $('detail').replaceChildren();const placeholder=el('div','detail-placeholder');placeholder.append(el('span',null,'✳'),el('strong',null,'Chọn một quan hệ'),el('p',null,'Nhấp vào đường nối hoặc một kết quả bên dưới để xem nguồn bằng chứng.'));$('detail').append(placeholder);
    if(facts.length)selectFact(0);
  }
  function renderFacts(){
    const list=$('factsList');list.replaceChildren();
    if(!state.facts.length){list.append(el('div','muted','Chưa có quan hệ phù hợp.'));list.lastChild.style.padding='20px';return;}
    state.facts.forEach((f,i)=>{
      const row=el('button','fact-row');row.type='button';row.dataset.index=i;
      row.append(el('span','fact-index',String(i+1).padStart(2,'0')));
      const body=el('div');const headline=el('div','fact-text');headline.append(el('span',null,f.subject.name),el('span','rel',`⟶ ${f.predicate} ⟶`),el('span',null,f.object.name));
      body.append(headline,el('div','fact-sub',`${f.subject.type} · ${f.object.type}  |  ${(f.doc_ids||[]).length} tài liệu`));
      row.append(body,el('span','fact-chevron','›'));row.addEventListener('click',()=>selectFact(i));list.append(row);
    });
  }
  function selectFact(index){
    state.selected=index;
    document.querySelectorAll('.fact-row').forEach(r=>r.classList.toggle('selected',Number(r.dataset.index)===index));
    document.querySelectorAll('[data-edge-index]').forEach(r=>r.classList.toggle('selected-edge',Number(r.dataset.edgeIndex)===index));
    const f=state.facts[index];if(!f)return;
    const detail=$('detail');detail.replaceChildren();
    detail.append(el('div','detail-kicker',`QUAN HỆ ${String(index+1).padStart(2,'0')}`),el('h4','detail-title',`${f.subject.name} → ${f.object.name}`));
    const triple=el('div','triple');triple.append(el('span','entity',f.subject.name),el('span','predicate',f.predicate),el('span','entity',f.object.name));detail.append(triple);
    detail.append(document.createElement('hr'));detail.lastChild.className='divider';
    detail.append(el('div','section-title',`BẰNG CHỨNG · ${(f.evidence||[]).length}`));
    const evidence=f.evidence||[];
    if(evidence.length){for(const e of evidence){const item=el('div','evidence-item');item.append(el('div','source',`${e.doc_id} · ${e.evidence_id}`),el('p',null,e.text||'Chưa có nội dung bằng chứng.'));detail.append(item);}}
    else detail.append(el('p','muted','Chưa lấy được văn bản bằng chứng. Kiểm tra MongoDB hoặc mã bằng chứng của quan hệ.'));
    if(f.doc_ids?.length){detail.append(el('div','section-title','TÀI LIỆU NGUỒN'));for(const d of f.doc_ids)detail.append(el('div','muted',d));}
    detail.scrollTop=0;
  }
  function renderGraph(nodes,facts){
    const area=$('graph'),canvas=$('graphSvg');
    show('graphEmpty',!facts.length);
    if(!facts.length){canvas.replaceChildren();state.graphControl=null;return;}
    const displayed=facts.slice(0,65);
    const used=new Set(displayed.flatMap(f=>[f.subject.id,f.object.id]));
    const visible=nodes.filter(n=>used.has(n.id)).map(n=>({id:n.id,name:n.name,type:n.type||'Entity',linked:state.anchorIds.has(n.id)}));
    const edges=displayed.map(f=>({source:f.subject.id,target:f.object.id,type:f.predicate}));
    state.graphControl=window.KGGraph.render(canvas,{nodes:visible,edges,width:area.clientWidth,height:area.clientHeight,
      onEdge:selectFact,onNode:n=>{const i=displayed.findIndex(f=>f.subject.id===n.id||f.object.id===n.id);if(i>=0)selectFact(i);}});
    $('graphEmpty').textContent=facts.length>displayed.length
      ?`Chỉ hiển thị ${displayed.length} quan hệ đầu tiên; xem đầy đủ trong danh sách.`:'';
  }
  $('queryZoomIn').addEventListener('click',()=>state.graphControl?.zoom(1.25));
  $('queryZoomOut').addEventListener('click',()=>state.graphControl?.zoom(1/1.25));
  $('queryFit').addEventListener('click',()=>state.graphControl?.fit());
  const queryPanel=$('graph').closest('.graph-card');
  $('queryFullscreen').addEventListener('click',async()=>{await window.KGGraph.toggleFullscreen(queryPanel);requestAnimationFrame(updateGraphSize);});
  function updateGraphSize(){state.graphControl?.resize($('graph').clientWidth,$('graph').clientHeight);$('queryFullscreen').setAttribute('aria-label',document.fullscreenElement===queryPanel||queryPanel.classList.contains('kg-fullscreen')?'Thoát toàn màn hình':'Toàn màn hình');}
  document.addEventListener('fullscreenchange',()=>requestAnimationFrame(updateGraphSize));
  window.addEventListener('resize',updateGraphSize);
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape'&&queryPanel.classList.contains('kg-fullscreen')){queryPanel.classList.remove('kg-fullscreen');requestAnimationFrame(updateGraphSize);}});
  $('exportBtn').addEventListener('click',()=>{
    if(!state.result)return;const blob=new Blob([JSON.stringify(state.result,null,2)],{type:'application/json'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='kg_query_result.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  setMode('related');
})();
