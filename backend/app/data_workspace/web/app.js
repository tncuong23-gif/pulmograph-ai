(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, text, className) => {const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node;};
  const groups = {
    overview: {title: 'Tổng quan dữ liệu'},
    rag: {title: 'Kho tri thức RAG', tabs: [['import', 'Nạp dữ liệu'], ['search', 'Tra cứu tri thức'], ['documents', 'Kho tài liệu']]},
    kg: {title: 'Knowledge Graph', tabs: [['import', 'Nạp dữ liệu'], ['explore', 'Khám phá đồ thị'], ['review', 'Rà soát trùng'], ['file', 'Xem trước JSON']]},
    context: {title: 'Context & Patient', tabs: [['import', 'Nạp dữ liệu'], ['history', 'Lịch sử & dữ kiện'], ['tools', 'Kiểm tra ngữ cảnh']]},
    reports: {title: 'Lịch sử & báo cáo'}
  };
  const names = {rag: 'RAG', kg: 'Knowledge Graph', context: 'Context & Patient'};
  const modes = {commit: 'Nạp dữ liệu', retry: 'Nạp lại file lỗi', preview: 'Xem trước', dry_run: 'Xem trước', validate: 'Kiểm tra file', index: 'Chuẩn bị chỉ mục'};
  const states = {completed: 'Đã xử lý', failed: 'Tác vụ lỗi', interrupted: 'Đã gián đoạn', running: 'Đang xử lý', queued: 'Đang chờ'};
  const entries = new Map();
  const terminal = status => ['completed', 'failed', 'interrupted'].includes(status);
  const attention = job => (job.failed || 0) + (job.partial || 0) + (job.needs_review || 0) > 0 || ['failed', 'interrupted'].includes(job.status);
  const validJob = id => /^[A-Za-z0-9_-]{1,128}$/.test(id || '');
  let route = {group: 'overview', view: '', job: null}, jobs = [], jobErrors = {}, reportPage = 0;
  let jobsPending = null, overviewPending = null, pollTimer, frameTimer, currentFrame = null;
  const localTime = value => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString('vi-VN') : '—';

  async function request(path) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(path, {signal: controller.signal});
      if (!response.ok) throw Error('Chưa đọc được dữ liệu. Kiểm tra backend rồi thử lại.');
      return await response.json();
    } catch (error) {
      if (error.name === 'AbortError') throw Error('Dịch vụ phản hồi chậm. Bạn có thể thử làm mới sau.');
      throw error;
    } finally {clearTimeout(timer);}
  }
  function feedback(message = '') {$('feedback').textContent = message; $('feedback').hidden = !message;}
  function parseRoute() {
    const [path, query = ''] = location.hash.replace(/^#/, '').split('?');
    let [group, view] = path.split('/');
    if (!Object.hasOwn(groups, group)) group = 'overview';
    const tabs = groups[group].tabs;
    if (tabs && !tabs.some(([id]) => id === view)) view = tabs[0][0];
    const job = new URLSearchParams(query).get('job');
    return {group, view: tabs ? view : '', job: validJob(job) ? job : null};
  }
  function frameSpec() {
    if (route.group === 'rag') return {key: 'rag', path: '/modules/rag/', view: route.view};
    if (route.view === 'import') return {key: route.group + '-import', path: '/imports', module: route.group, view: 'import'};
    if (route.group === 'kg') return route.view === 'explore' ? {key: 'kg-explore', path: '/modules/kg-explorer/', view: 'explore'} : {key: 'kg-review', path: '/modules/kg-explorer/duplicates', view: route.view === 'file' ? 'file' : 'graph'};
    return {key: 'context', path: '/modules/context/ui', view: route.view};
  }
  function send(entry) {
    if (entry.ready) entry.frame.contentWindow?.postMessage({type: 'medical-data:view', view: entry.view, job: entry.job}, location.origin);
  }
  function frameStatus(entry) {
    if (currentFrame !== entry) return;
    $('frameStatus').hidden = entry.ready;
    $('frameMessage').textContent = entry.error || 'Đang mở giao diện dữ liệu…';
    $('retryFrame').hidden = !entry.error;
  }
  function showModule() {
    const spec = frameSpec();
    for (const entry of entries.values()) entry.frame.hidden = true;
    let entry = entries.get(spec.key);
    if (!entry) {
      const frame = el('iframe');
      frame.title = groups[route.group].title + ' · ' + groups[route.group].tabs.find(([id]) => id === route.view)[1];
      frame.setAttribute('allowfullscreen', '');
      const params = new URLSearchParams({embed: '1', view: spec.view});
      if (spec.module) params.set('module', spec.module);
      if (route.job) params.set('job', route.job);
      entry = {key: spec.key, frame, ready: false, view: spec.view, job: route.job, error: null};
      entries.set(spec.key, entry);
      frame.addEventListener('load', () => {
        try {
          if (frame.contentDocument?.documentElement?.dataset.workspaceEmbedded === 'true') {entry.ready = true; entry.error = null; send(entry);}
          else entry.error = 'Chưa mở được module này. Kiểm tra kết nối dịch vụ và log khởi động backend, rồi thử lại.';
        } catch {entry.error = 'Không đọc được giao diện module. Kiểm tra địa chỉ backend và cấu hình truy cập.';}
        frameStatus(entry);
      });
      frame.src = spec.path + '?' + params;
      $('frames').append(frame);
    } else {entry.view = spec.view; entry.job = route.job; send(entry);}
    currentFrame = entry; entry.frame.hidden = false; frameStatus(entry);
    clearTimeout(frameTimer);
    if (!entry.ready) frameTimer = setTimeout(() => {
      if (!entry.ready) {entry.error = 'Module mở chậm hoặc chưa sẵn sàng. Kiểm tra dịch vụ phụ thuộc rồi thử mở lại.'; frameStatus(entry);}
    }, 12000);
  }
  $('retryFrame').addEventListener('click', () => {
    if (!currentFrame) return;
    entries.delete(currentFrame.key); currentFrame.frame.remove(); currentFrame = null; showModule();
  });
  function openJob(job) {
    const next = '#' + job.module + '/import?job=' + encodeURIComponent(job.job_id);
    if (location.hash === next) navigate(); else location.hash = next;
  }
  function mobile() {return window.matchMedia('(max-width: 740px)').matches;}
  function updateToggle() {
    const expanded = mobile() ? $('shell').classList.contains('mobile-open') : !$('shell').classList.contains('collapsed');
    $('toggleNav').setAttribute('aria-expanded', String(expanded));
    $('navigation').inert = mobile() && !expanded;
  }
  function closeMobile() {$('shell').classList.remove('mobile-open'); $('navBackdrop').hidden = true; updateToggle();}
  $('toggleNav').addEventListener('click', () => {
    if (mobile()) {$('shell').classList.toggle('mobile-open'); $('navBackdrop').hidden = !$('shell').classList.contains('mobile-open');}
    else $('shell').classList.toggle('collapsed');
    updateToggle();
    currentFrame?.frame.contentWindow?.postMessage({type: 'medical-data:view', view: currentFrame.view, job: null}, location.origin);
  });
  $('navBackdrop').addEventListener('click', closeMobile);
  window.addEventListener('resize', () => {if (!mobile()) closeMobile(); else updateToggle();});
  document.addEventListener('keydown', event => {if (event.key === 'Escape' && $('shell').classList.contains('mobile-open')) {closeMobile(); $('toggleNav').focus();}});

  const metricNames = {rag: [['documents','Tài liệu'],['chunks','Đoạn nội dung'],['propositions','Mệnh đề'],['vectors','Vector']], kg: [['entities','Thực thể'],['relations','Quan hệ'],['documents','Tài liệu nguồn']], context: [['patients','Bệnh nhân'],['sessions','Phiên'],['turns','Lượt hội thoại'],['facts','Dữ kiện']]};
  function renderOverview(data) {
    $('moduleCards').replaceChildren();
    for (const module of ['rag', 'kg', 'context']) {
      const value = data.modules?.[module] || {state: 'unavailable', message: 'Chưa đọc được dữ liệu.'};
      const card = el('article', null, 'module-card'); card.dataset.module = module;
      const heading = el('div', null, 'card-title'); heading.append(el('h3', names[module]));
      let state = value.state, label = {ready: 'Sẵn sàng', busy: 'Đang xử lý', unavailable: 'Chưa kết nối'}[state] || 'Chưa xác định';
      if (value.mode === 'demo' || value.mode === 'memory') {state = 'attention'; label = value.mode === 'demo' ? 'Chế độ demo' : 'Bộ nhớ tạm';}
      if (module === 'kg' && state === 'ready' && (value.mongodb?.state !== 'ready' || value.vector?.state !== 'ready')) {state = 'attention'; label = 'Cần kiểm tra';}
      heading.append(el('span', label, 'badge ' + state)); card.append(heading, el('p', value.message, 'card-description'));
      const metrics = el('div', null, 'metrics');
      for (const [key, name] of metricNames[module]) {
        const metric = el('div', null, 'metric'), count = value.stats?.[key];
        metric.append(el('strong', typeof count === 'number' ? count.toLocaleString('vi-VN') : '—'), el('span', name)); metrics.append(metric);
      }
      card.append(metrics);
      const notes = [];
      if (module === 'rag') {
        if (value.chunking) notes.push('Chia đoạn: ' + (value.chunking === 'semantic' ? 'theo ngữ nghĩa' : 'theo token') + '.');
        if (value.stats?.needs_reindex) notes.push('Có tài liệu cần xây dựng lại chỉ mục.');
      }
      if (module === 'kg') {
        if (value.mongodb?.message) notes.push(value.mongodb.message);
        if (value.vector?.message) notes.push('Qdrant: ' + value.vector.message);
        if (typeof value.vector?.points === 'number') notes.push(value.vector.points.toLocaleString('vi-VN') + ' vector tên thực thể.');
      }
      if (module === 'context') notes.push('Dữ kiện nạp vào Patient Graph cần được xem trước và xác nhận.');
      card.append(el('p', notes.join('\n'), 'card-note'));
      const link = el('a', 'Mở không gian dữ liệu →', 'card-link'); link.href = '#' + module + '/import'; card.append(link);
      $('moduleCards').append(card);
    }
    $('checkedAt').textContent = 'Kiểm tra lúc ' + localTime(data.checked_at);
  }
  function loadOverview() {
    if (overviewPending) return overviewPending;
    overviewPending = request('/api/v1/data/overview').then(renderOverview).catch(error => {feedback(error.message); $('checkedAt').textContent = 'Chưa cập nhật được kết nối';}).finally(() => {overviewPending = null;});
    return overviewPending;
  }
  function renderTable(target, items, compact = false) {
    target.replaceChildren();
    if (!items.length) {target.append(el('div', 'Chưa có lượt nạp phù hợp. Chọn một nguồn dữ liệu để bắt đầu.', 'empty')); return;}
    const scroll = el('div', null, 'table-scroll'), table = el('table'), head = el('thead'), headRow = el('tr'), body = el('tbody');
    for (const title of ['Nguồn / thời gian', 'Thao tác', 'Kết quả', 'Chi tiết']) headRow.append(el('th', title));
    head.append(headRow); table.append(head, body);
    for (const job of items) {
      const row = el('tr'), identity = el('td');
      identity.append(el('strong', names[job.module] || job.module), el('small', localTime(job.started_at)));
      if (!compact) {const code = el('code', job.job_id); code.title = job.job_id; identity.append(code);}
      const mode = el('td', modes[job.mode] || job.mode); mode.append(el('small', (job.processed || 0) + '/' + (job.total || 0) + ' file'));
      const status = el('td');
      const active = !terminal(job.status), needsReview = attention(job);
      status.append(el('span', active ? (states[job.status] || job.status) : needsReview ? 'Cần kiểm tra' : (states[job.status] || job.status), 'badge ' + (active ? 'busy' : needsReview ? 'attention' : 'ready')));
      status.append(el('small', `${job.completed || 0} đạt · ${job.skipped || 0} đã có · ${(job.failed || 0) + (job.partial || 0)} lỗi${job.needs_review ? ' · ' + job.needs_review + ' cần duyệt' : ''}`));
      const actionsCell = el('td'), actions = el('div', null, 'table-actions'), open = el('button', 'Mở lượt →');
      open.type = 'button'; open.addEventListener('click', () => openJob(job)); actions.append(open);
      if (!compact && terminal(job.status)) {
        const base = job.module === 'rag' ? '/modules/rag/api/v1/rag/batch/jobs/' : '/api/v1/imports/' + job.module + '/jobs/';
        for (const [kind, title] of [['json', 'JSON'], ['csv', 'CSV'], ['errors', 'File lỗi']]) {
          const link = el('a', title); link.href = base + encodeURIComponent(job.job_id) + '/report?kind=' + kind; link.download = ''; actions.append(link);
        }
      }
      actionsCell.append(actions); row.append(identity, mode, status, actionsCell); body.append(row);
    }
    scroll.append(table); target.append(scroll);
  }
  function renderReports() {
    const module = $('moduleFilter').value, status = $('statusFilter').value, query = $('jobSearch').value.trim().toLowerCase();
    const filtered = jobs.filter(job => (module === 'all' || job.module === module) && (!query || job.job_id.toLowerCase().includes(query)) && (status === 'all' || status === 'active' && !terminal(job.status) || status === 'attention' && attention(job) || status === 'done' && terminal(job.status)));
    const pages = Math.max(1, Math.ceil(filtered.length / 15)); reportPage = Math.min(reportPage, pages - 1);
    renderTable($('jobsTable'), filtered.slice(reportPage * 15, reportPage * 15 + 15)); renderTable($('recentJobs'), jobs.slice(0, 5), true);
    const active = jobs.filter(job => !terminal(job.status)).length;
    $('activeCount').textContent = active ? active + ' lượt đang xử lý' : 'Không có lượt đang chạy';
    $('activeCount').className = 'badge' + (active ? ' busy' : '');
    $('reportCount').textContent = filtered.length + ' lượt nạp'; $('pageNumber').textContent = (reportPage + 1) + ' / ' + pages;
    $('previousPage').disabled = reportPage === 0; $('nextPage').disabled = reportPage === pages - 1;
    const warnings = Object.keys(jobErrors).map(key => (names[key] || key) + ': ' + jobErrors[key]);
    $('reportWarnings').textContent = warnings.join(' '); $('reportWarnings').hidden = !warnings.length;
    if (warnings.length && route.group === 'overview') feedback('Chưa tải được lịch sử của một số nguồn. Xem mục Lịch sử & báo cáo để biết chi tiết.');
  }
  function loadJobs() {
    if (jobsPending) return jobsPending;
    clearTimeout(pollTimer);
    jobsPending = request('/api/v1/data/jobs').then(data => {jobs = data.items || []; jobErrors = data.errors || {}; renderReports();}).catch(error => feedback(error.message)).finally(() => {
      jobsPending = null;
      if (['overview', 'reports'].includes(route.group) && jobs.some(job => !terminal(job.status))) pollTimer = setTimeout(loadJobs, 5000);
    });
    return jobsPending;
  }
  function navigate() {
    route = parseRoute(); feedback(); closeMobile(); clearTimeout(pollTimer);
    $('pageTitle').textContent = groups[route.group].title; document.title = groups[route.group].title + ' · Medical AI';
    document.querySelectorAll('#primaryNav a').forEach(link => {const active = link.dataset.group === route.group; link.classList.toggle('active', active); if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');});
    $('subnav').replaceChildren(); $('subnav').hidden = !groups[route.group].tabs;
    for (const [view, title] of groups[route.group].tabs || []) {const link = el('a', title); link.href = '#' + route.group + '/' + view; if (view === route.view) {link.className = 'active'; link.setAttribute('aria-current', 'page');} $('subnav').append(link);}
    const native = ['overview', 'reports'].includes(route.group);
    $('overview').hidden = route.group !== 'overview'; $('reports').hidden = route.group !== 'reports'; $('modulePanel').hidden = native; $('refresh').hidden = !native;
    if (native) {currentFrame = null; clearTimeout(frameTimer); loadJobs(); if (route.group === 'overview') loadOverview();}
    else showModule();
  }
  async function setupReturnLink() {
    try {
      const requested = new URLSearchParams(location.search).get('return_to');
      if (!requested) return;
      const target = new URL(requested), config = await request('/api/v1/data/config');
      if (['http:', 'https:'].includes(target.protocol) && !target.username && !target.password && config.frontend_origins.includes(target.origin)) {
        $('backToChat').href = target.origin + '/chat'; $('backToChat').lastElementChild.textContent = 'Trở về hội thoại';
      }
    } catch { /* Keep the backend services link if the frontend origin is unavailable. */ }
  }
  $('refresh').addEventListener('click', () => {feedback(); loadJobs(); if (route.group === 'overview') loadOverview();});
  for (const id of ['moduleFilter', 'statusFilter', 'jobSearch']) $(id).addEventListener(id === 'jobSearch' ? 'input' : 'change', () => {reportPage = 0; renderReports();});
  $('previousPage').addEventListener('click', () => {reportPage = Math.max(0, reportPage - 1); renderReports();});
  $('nextPage').addEventListener('click', () => {reportPage++; renderReports();});
  window.addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    const entry = [...entries.values()].find(item => item.frame.contentWindow === event.source);
    if (!entry) return;
    if (event.data?.type === 'medical-data:ready') {entry.ready = true; entry.error = null; send(entry); frameStatus(entry);}
    if (event.data?.type === 'medical-data:notice' && currentFrame === entry && typeof event.data.message === 'string') feedback(event.data.message.slice(0, 500));
  });
  window.addEventListener('hashchange', navigate);
  window.addEventListener('beforeunload', () => {clearTimeout(pollTimer); clearTimeout(frameTimer);});
  navigate(); setupReturnLink();
})();
