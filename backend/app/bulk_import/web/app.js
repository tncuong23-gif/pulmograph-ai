(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const module = new URLSearchParams(location.search).get('module') === 'context' ? 'context' : 'kg';
  const base = `/api/v1/imports/${module}`;
  const labels = {pending:'Chờ xử lý',running:'Đang xử lý',completed:'Hoàn tất',skipped:'Đã có',failed:'Lỗi',partial:'Ghi một phần',needs_review:'Cần duyệt',queued:'Đã xếp lượt',interrupted:'Bị gián đoạn'};
  const modes = {validate:'Kiểm tra',preview:'Xem trước',commit:'Nạp dữ liệu',retry:'Thử lại',index:'Đồng bộ chỉ mục'};
  let files = [], job = null, busy = false, page = 0, timer = null;
  const selected = new Set();
  const elem = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const error = message => { $('error').textContent = message || ''; $('error').hidden = !message; };
  const terminal = value => ['completed','failed','interrupted'].includes(value);
  const eligible = row => job?.mode === 'preview' && job.status === 'completed' && row.status === 'completed';
  async function api(path, options = {}) {
    const response = await fetch(base + path, options);
    let data; try { data = await response.json(); } catch { throw new Error(`Máy chủ trả phản hồi không hợp lệ (HTTP ${response.status}).`); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data));
    return data;
  }
  const post = (path, body) => api(path, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  function controls() {
    const working = busy || (job && !terminal(job.status));
    $('files').disabled = !!working;
    for (const id of ['folderPreview','indexKg']) $(id).disabled = !!working;
    $('validateFiles').disabled = $('previewFiles').disabled = !!working || !files.length;
    const canCommit = job?.mode === 'preview' && job.status === 'completed';
    const canRetry = ['commit','retry'].includes(job?.mode) && terminal(job?.status) && (job.failed + job.partial > 0);
    $('approval').hidden = !canCommit && !canRetry;
    $('commit').hidden = !canCommit;
    $('commit').disabled = !!working || !$('confirm').checked || !selected.size;
    $('retry').hidden = !canRetry;
    $('retry').disabled = !!working || !$('confirm').checked;
    $('repreview').hidden = !job || !terminal(job.status) || job.mode === 'index';
    $('repreview').disabled = !!working;
    $('selectAll').disabled = !canCommit || !job.items.some(eligible);
    const candidates = job?.items.filter(eligible) || [];
    $('selectAll').checked = candidates.length > 0 && candidates.every(row => selected.has(row.filename));
    $('selectAll').indeterminate = candidates.some(row => selected.has(row.filename)) && !$('selectAll').checked;
  }
  function choose(input) {
    if (busy || (job && !terminal(job.status))) return;
    const names = new Set(); const chosen = []; const issues = [];
    for (const file of input) {
      if (!/\.json$/i.test(file.name)) { issues.push(`${file.name}: chỉ nhận JSON.`); continue; }
      if (names.has(file.name.toLowerCase())) { issues.push(`${file.name}: tên file trùng, chỉ giữ file đầu tiên.`); continue; }
      names.add(file.name.toLowerCase()); chosen.push(file);
    }
    if (chosen.length > 10000) { error('Mỗi lượt tối đa 10.000 file.'); return; }
    files = chosen;
    $('selectedFiles').replaceChildren(elem('strong',`${files.length} file được chọn`));
    for (const file of files.slice(0,100)) $('selectedFiles').append(elem('div', `${file.name} · ${(file.size/1024).toFixed(1)} KiB`));
    if (files.length > 100) $('selectedFiles').append(elem('div',`… và ${files.length-100} file khác.`));
    error(issues.join('\n')); controls();
  }
  async function launch(body) {
    const value = await post('/jobs',body);
    selected.clear(); $('confirm').checked = false; page = 0;
    job = value; render(); poll();
  }
  async function run(operation) {
    if (busy) return;
    busy = true; controls(); error('');
    try { await operation(); } catch(e) { error(e.message); }
    finally { busy = false; controls(); }
  }
  async function uploadAndPreview(mode) {
    const file_errors = {}, names = files.map(f=>f.name);
    for (let i=0;i<files.length;i++) {
      const file = files[i]; $('selectedFiles').textContent = `Đang tải ${i+1}/${files.length}: ${file.name}`;
      try {
        if (file.size > 20*1024*1024) throw new Error('File vượt quá 20 MiB.');
        await api('/uploads/'+encodeURIComponent(file.name), {method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file});
      } catch(e) { file_errors[file.name] = e.message; }
    }
    $('selectedFiles').textContent = `Đã tải ${files.length-Object.keys(file_errors).length}/${files.length} file. Kết quả tải lỗi được ghi trong báo cáo.`;
    await launch({source:'files',mode,files:names,file_errors});
  }
  function render() {
    if (!job) return;
    $('jobMeta').textContent = `${modes[job.mode]} · ${labels[job.status]} · ${job.processed}/${job.total} file` + (job.current_file?` · ${job.current_file}`:'');
    $('progress').max = Math.max(1,job.total); $('progress').value = job.processed;
    $('metrics').replaceChildren();
    for (const [key,label] of [['completed',job.mode==='preview'?'ĐỦ ĐIỀU KIỆN':'HOÀN TẤT'],['skipped','ĐÃ CÓ'],['failed','LỖI'],['partial','GHI MỘT PHẦN'],['needs_review','CẦN DUYỆT']]) {
      const box=elem('div',undefined,'metric'); box.append(elem('span',label),elem('strong',String(job[key]||0))); $('metrics').append(box);
    }
    $('rows').replaceChildren();
    const pages = Math.max(1,Math.ceil(job.items.length/100)); page = Math.min(page,pages-1);
    for (const row of job.items.slice(page*100,(page+1)*100)) {
      const tr=elem('tr'), tick=elem('input'); tick.type='checkbox'; tick.disabled=!eligible(row);
      tick.checked=selected.has(row.filename); tick.setAttribute('aria-label',`Chọn ${row.filename}`);
      tick.addEventListener('change',()=>{ if(tick.checked)selected.add(row.filename);else selected.delete(row.filename); controls(); });
      const selectCell=elem('td'); selectCell.append(tick);
      const name=elem('td',row.filename); if(row.record_id)name.append(elem('small',row.record_id));
      const status=elem('td');status.append(elem('span',job.mode==='preview'&&row.status==='completed'?'Có thể xác nhận':labels[row.status],`status ${row.status}`));
      const detail=elem('td',row.error || (row.candidate_count?`${row.candidate_count} thực thể cần duyệt`:''));
      if(row.statistics)detail.append(elem('small',JSON.stringify(row.statistics)));
      if(module==='kg' && row.review_status){
        status.append(elem('span',({reviewed:'Đã duyệt',needs_review:'Cần duyệt',unreviewed:'Chưa đánh dấu duyệt'})[row.review_status],`status review-${row.review_status}`));
        if(row.reviewed_at)status.append(elem('small',new Date(row.reviewed_at).toLocaleString('vi-VN')));
      }
      if(row.elapsed_seconds!==undefined)detail.append(elem('small',`Thời gian xử lý: ${row.elapsed_seconds.toFixed(1)} giây`));
      if(row.warning)detail.append(elem('small',row.warning));
      if(row.storage==='memory')detail.append(elem('small','Chế độ memory: dữ liệu mất khi backend dừng.'));
      if(row.stage)detail.append(elem('small',`Bước: ${row.stage}`));
      const reviewCell=elem('td');
      if(job.mode==='preview'&&job.status==='completed'&&['completed','needs_review'].includes(row.status)) {
        const button=elem('button',module==='context'?'Xem dữ kiện':'Xem / duyệt','text-button');button.type='button';
        button.addEventListener('click',()=>run(()=>review(row)));reviewCell.append(button);
      }
      tr.append(selectCell,name,status,detail,reviewCell);$('rows').append(tr);
    }
    $('pageInfo').textContent=`Trang ${page+1}/${pages}`;$('prevPage').disabled=page===0;$('nextPage').disabled=page===pages-1;
    $('reports').replaceChildren();
    for(const[k,label]of[['json','Tải JSON'],['csv','Tải CSV đầy đủ'],['errors','Tải danh sách lỗi / cần duyệt']]){
      const a=elem('a',label);a.href=`${base}/jobs/${encodeURIComponent(job.job_id)}/report?kind=${k}`;a.download='';$('reports').append(a);
    }
    if(job.error)error(job.error);
    controls();
  }
  async function history() {
    const data=await api('/jobs');$('history').replaceChildren();
    for(const row of data.items){
      const button=elem('button');button.type='button';button.append(elem('span',`${modes[row.mode]} · ${labels[row.status]} · ${row.total} file`),elem('span',new Date(row.started_at).toLocaleString('vi-VN')));
      button.addEventListener('click',()=>run(async()=>{clearTimeout(timer);job=await api(`/jobs/${row.job_id}`);selected.clear();$('confirm').checked=false;page=0;render();poll();}));$('history').append(button);
    }
    if(!data.items.length)$('history').append(elem('p','Chưa có lượt nào.','muted'));
    return data;
  }
  function poll() {
    clearTimeout(timer);
    if(!job||terminal(job.status)){history().catch(e=>error(e.message));return;}
    timer=setTimeout(async()=>{
      try{const id=job.job_id;const value=await api(`/jobs/${id}`);if(job?.job_id!==id)return;job=value;render();poll();}
      catch(e){error(`Chưa cập nhật được tiến độ: ${e.message} Bấm Làm mới để theo dõi lại.`);}
    },1200);
  }
  async function refresh() {
    const data=await history();
    const requested=new URLSearchParams(location.search).get('job');
    const id=job?.job_id||(/^[A-Za-z0-9_-]{1,128}$/.test(requested||'')?requested:null)||data.active_job_id||data.items[0]?.job_id;
    if(id){job=await api(`/jobs/${id}`);render();poll();}
  }
  async function review(row) {
    const currentJob=job.job_id;
    const data=await api(`/jobs/${currentJob}/items/${row.position}/preview`);
    $('reviewTitle').textContent=`Xem trước · ${row.filename}`;$('reviewBody').replaceChildren();$('reviewFeedback').textContent='';
    if(module==='context'){
      $('reviewBody').append(elem('p',`Bệnh nhân: ${data.patient_id} · Phiên: ${data.session_id}. Kiểm tra nguồn, phủ định, mức độ chắc chắn và các giá trị trước khi xác nhận.`));
      const pre=elem('pre',JSON.stringify({patient_id:data.patient_id,session_id:data.session_id,facts:data.facts,history:data.history},null,2));$('reviewBody').append(pre);
    }else{
      $('reviewBody').append(elem('p',`Tài liệu: ${data.document_id}`));
      if(data.review_status==='reviewed')$('reviewBody').append(elem('p',`Đã duyệt · ${new Date(data.reviewed_at).toLocaleString('vi-VN')}`,'review-receipt'));
      const candidates=data.plan.entity_candidates||{}, choices={}, entries=Object.entries(candidates);
      const names=Object.fromEntries(data.entities.map(e=>[e.id,e.canonical_name]));
      const actions=elem('div',undefined,'actions review-actions'), count=elem('span','', 'muted');
      const save=elem('button','Lưu duyệt tài liệu');save.type='button';save.dataset.action='save-review';
      const keepAll=elem('button','Giữ lại tất cả thực thể','secondary');keepAll.type='button';keepAll.dataset.action='keep-all';
      keepAll.hidden=!entries.length;
      const candidateList=elem('div'), pager=elem('div',undefined,'pager');
      const prev=elem('button','← Trước','text-button'),next=elem('button','Tiếp →','text-button'),pageLabel=elem('span');
      prev.type=next.type='button';let reviewPage=0,saving=false;
      const updateCount=()=>{count.textContent=`Đã chọn ${Object.keys(choices).length}/${entries.length} thực thể`;};
      const draw=()=>{
        candidateList.replaceChildren();
        for(const[eid,options]of entries.slice(reviewPage*100,(reviewPage+1)*100)){
          const box=elem('div',undefined,'candidate'),label=elem('label',`${names[eid]||eid} (${eid})`),select=elem('select');
          select.id=`choice-${eid}`;label.htmlFor=select.id;select.disabled=saving;
          select.append(new Option('Chọn cách xử lý…',''),new Option('Giữ là thực thể riêng','new'));
          for(const c of options){if(c.link_allowed===false){box.append(elem('p',`Khác loại: ${c.canonical_name} (${c.entity_type}). Sửa loại trong JSON nếu cùng khái niệm; chỉ giữ riêng khi khác khái niệm.`));continue;}select.append(new Option(`${c.canonical_name} · ${c.entity_id} · điểm ${c.score}`,c.entity_id));}
          select.value=choices[eid]||'';
          select.addEventListener('change',()=>{if(select.value)choices[eid]=select.value;else delete choices[eid];updateCount();});
          box.append(label,select);candidateList.append(box);
        }
        const pages=Math.max(1,Math.ceil(entries.length/100));
        pager.hidden=pages===1;prev.disabled=saving||reviewPage===0;next.disabled=saving||reviewPage===pages-1;
        pageLabel.textContent=`Trang ${reviewPage+1}/${pages}`;updateCount();
      };
      keepAll.addEventListener('click',()=>{for(const[eid,options]of entries)if(!options.some(c=>c.link_allowed===false))choices[eid]='new';draw();$('reviewFeedback').textContent='Đã chọn giữ riêng các ứng viên cùng loại. Ứng viên khác loại phải duyệt từng mục. Có thể chỉnh từng mục rồi bấm Lưu duyệt tài liệu.';});
      prev.addEventListener('click',()=>{reviewPage--;draw();});next.addEventListener('click',()=>{reviewPage++;draw();});
      save.addEventListener('click',async()=>{
        if(saving)return;
        if(Object.keys(choices).length!==entries.length){$('reviewFeedback').textContent='Chọn cách xử lý cho tất cả thực thể trong file này.';return;}
        saving=true;save.disabled=keepAll.disabled=true;draw();$('reviewFeedback').textContent='Đang kiểm tra và lưu duyệt tài liệu…';
        try{
          const result=await post(`/jobs/${currentJob}/items/${row.position}/decisions`,{choices});
          $('reviewFeedback').textContent=result.message;
          if(job?.job_id===currentJob){
            if(result.item){
              job.items=job.items.map(item=>item.position===row.position?result.item:item);
              for(const key of ['completed','skipped','failed','partial','needs_review'])job[key]=job.items.filter(item=>item.status===key).length;
            }else job=await api(`/jobs/${currentJob}`);
            selected.delete(row.filename);$('confirm').checked=false;render();
          }
          files=[];$('files').value='';$('selectedFiles').textContent='Đã lưu bản đã duyệt vào file nguồn. Chọn các tài liệu sẵn sàng trong bảng để xác nhận nạp.';controls();
          save.textContent='Đã duyệt';save.disabled=keepAll.disabled=true;
          history().catch(()=>{});
        }catch(e){$('reviewFeedback').textContent=e.message;saving=false;save.disabled=keepAll.disabled=false;draw();}
      });
      actions.append(keepAll,save,count);pager.append(prev,pageLabel,next);
      $('reviewBody').append(elem('p',entries.length?'Giữ riêng áp dụng cho các thực thể đang cần duyệt. Chọn ID gợi ý nếu muốn liên kết với thực thể đã có.':'Không có ứng viên cần chọn. Bấm Lưu duyệt tài liệu để đánh dấu bạn đã kiểm tra.'),actions,candidateList,pager);
      draw();
      const details=elem('details'),summary=elem('summary','Kế hoạch ghi dữ liệu');details.append(summary,elem('pre',JSON.stringify(data.plan,null,2)));$('reviewBody').append(details);
    }
    $('reviewDialog').showModal();
  }
  $('moduleTag').textContent=module==='kg'?'MongoDB · Neo4j · Qdrant':'History · Patient Graph';
  $('folderPath').textContent=`backend/data/import/${module}/`;
  $('notice').textContent=module==='kg'?'Thực thể tương đồng được đưa vào bước duyệt. Cập nhật vector cùng lượt nạp; lỗi đồng bộ được ghi riêng để thử lại.':'Mỗi file thuộc một bệnh nhân và một phiên. Dữ kiện chỉ được ghi sau khi bạn xác nhận; lịch sử không tự tạo dữ kiện bệnh nhân.';
  $('confirmText').textContent=module==='kg'?'Tôi đã xem trước và đồng ý nạp các file được chọn vào KG.':'Tôi đã kiểm tra đúng bệnh nhân, phiên hội thoại, nguồn và toàn bộ dữ kiện trong các file được chọn; tôi xác nhận ghi các dữ kiện này vào Patient Graph.';
  $('indexKg').hidden=module!=='kg';
  document.querySelector(`[data-tab="${module}"]`).classList.add('active');
  $('files').addEventListener('change',e=>choose(e.target.files));
  $('dropzone').addEventListener('dragover',e=>{e.preventDefault();$('dropzone').classList.add('drag');});
  $('dropzone').addEventListener('dragleave',()=>$('dropzone').classList.remove('drag'));
  $('dropzone').addEventListener('drop',e=>{e.preventDefault();$('dropzone').classList.remove('drag');choose(e.dataTransfer.files);});
  $('validateFiles').addEventListener('click',()=>run(()=>uploadAndPreview('validate')));
  $('previewFiles').addEventListener('click',()=>run(()=>uploadAndPreview('preview')));
  $('folderPreview').addEventListener('click',()=>run(()=>launch({mode:'preview',source:'directory'})));
  $('indexKg').addEventListener('click',()=>run(()=>launch({mode:'index'})));
  $('confirm').addEventListener('change',controls);
  $('selectAll').addEventListener('change',()=>{for(const row of job.items.filter(eligible)){if($('selectAll').checked)selected.add(row.filename);else selected.delete(row.filename);}render();});
  $('commit').addEventListener('click',()=>run(()=>launch({mode:'commit',previous_job_id:job.job_id,confirmed:$('confirm').checked,files:[...selected]})));
  $('retry').addEventListener('click',()=>run(()=>launch({mode:'retry',previous_job_id:job.job_id,confirmed:$('confirm').checked})));
  $('refresh').addEventListener('click',()=>run(refresh));
  $('repreview').addEventListener('click',()=>run(()=>launch({mode:'preview',source:'files',files:job.items.filter(row=>!row.upload_error).map(row=>row.filename)})));
  $('prevPage').addEventListener('click',()=>{page--;render();});$('nextPage').addEventListener('click',()=>{page++;render();});
  $('closeReview').addEventListener('click',()=>$('reviewDialog').close());
  window.addEventListener('beforeunload',()=>clearTimeout(timer));
  const initialized=run(refresh);
  document.addEventListener('medical-data:job',async event=>{
    const id=event.detail?.job;
    if(!/^[A-Za-z0-9_-]{1,128}$/.test(id||''))return;
    await initialized;
    if(job?.job_id===id)return;
    if(busy){error('Đang thực hiện thao tác. Chờ hoàn tất rồi mở lại lượt từ báo cáo.');return;}
    run(async()=>{clearTimeout(timer);job=await api('/jobs/'+encodeURIComponent(id));selected.clear();$('confirm').checked=false;page=0;render();poll();});
  });
})();
