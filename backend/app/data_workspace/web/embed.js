(() => {
  'use strict';
  const params = new URLSearchParams(location.search), path = location.pathname;
  const embedded = params.get('embed') === '1' && window.parent !== window;
  const type = path.startsWith('/modules/rag') ? 'rag' : path.startsWith('/modules/context') ? 'context' : path === '/imports' ? 'import' : path.includes('/duplicates') ? 'review' : 'kg';
  if (embedded) {
    document.documentElement.dataset.workspaceEmbedded = 'true';
    document.documentElement.dataset.workspaceModule = type;
  }
  document.addEventListener('DOMContentLoaded', () => {
    if (!embedded) {
      const route = type === 'rag' ? 'rag/import' : type === 'context' ? 'context/history' : type === 'import' ? (params.get('module') === 'context' ? 'context/import' : 'kg/import') : type === 'review' ? 'kg/review' : 'kg/explore';
      const link = document.createElement('a');
      link.className = 'data-workspace-link'; link.href = '/data#' + route; link.textContent = 'Quản lý dữ liệu →';
      document.body.append(link); return;
    }
    if (type === 'context') {
      for (const id of ['patientId', 'sessionId', 'question', 'turnText']) document.getElementById(id).value = '';
      document.getElementById('patientId').placeholder = 'Nhập Patient ID';
      document.getElementById('sessionId').placeholder = 'Nhập Session ID';
    }
    let view = null, initialJob = params.get('job');
    function activate(next, job) {
      if (next !== view) {
        if (type === 'rag' && ['import', 'search', 'documents'].includes(next)) document.querySelector(`[data-view="${next}"]`)?.click();
        if (type === 'review' && ['graph', 'file'].includes(next)) document.getElementById('tab-' + next)?.click();
        if (type === 'context' && ['history', 'tools'].includes(next)) {
          document.documentElement.dataset.contextView = next;
          document.querySelector(`[data-tab="${next === 'history' ? 'historyPanel' : 'jsonPanel'}"]`)?.click();
          document.querySelector('#contextResolveCard h2').textContent = next === 'history' ? 'Chọn bệnh nhân và phiên' : 'Kiểm tra xử lý ngữ cảnh';
        }
        view = next;
      }
      requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));
      if (/^[A-Za-z0-9_-]{1,128}$/.test(job || '') && job !== initialJob) document.dispatchEvent(new CustomEvent('medical-data:job', {detail: {job}}));
      initialJob = null;
    }
    activate(params.get('view'), params.get('job'));
    window.addEventListener('message', event => {
      if (event.source === window.parent && event.origin === location.origin && event.data?.type === 'medical-data:view') activate(event.data.view, event.data.job);
    });
    window.parent.postMessage({type: 'medical-data:ready'}, location.origin);
  }, {once: true});
})();
