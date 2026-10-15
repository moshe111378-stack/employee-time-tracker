(function () {
  'use strict';
  let running = false, dirty = false;
  document.addEventListener('input', event => {
    if (event.target.closest('#assignmentForm, .manual-edit-form')) dirty = true;
  });
  document.addEventListener('change', event => {
    if (event.target.closest('#assignmentForm, .manual-edit-form')) dirty = true;
  });
  async function refresh() {
    if (running || document.hidden || navigator.onLine === false) return;
    // Never replace a form the manager is reading/editing or a focused report.
    if (dirty || document.querySelector('#assignmentEditor[open], .manual-edit[open]') ||
        document.activeElement.closest('#assignmentPanel, #eventReports')) return;
    running = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(location.pathname, {credentials:'same-origin', cache:'no-store', signal:controller.signal});
      if (!response.ok || response.redirected) return;
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      // Recheck after the network await: the manager may have begun an edit.
      if (dirty || document.querySelector('#assignmentEditor[open], .manual-edit[open]') ||
          document.activeElement.closest('#assignmentPanel, #eventReports')) return;
      ['eventSummary','eventReports','assignmentPanel'].forEach(id => {
        const existing = document.getElementById(id), fresh = page.getElementById(id);
        if (existing && fresh && existing.innerHTML !== fresh.innerHTML) existing.innerHTML = fresh.innerHTML;
      });
      if (typeof applyReports === 'function') applyReports();
    } catch (_) {
      // Keep the last good view and any unsaved user input when offline.
    } finally { clearTimeout(timeout); running = false; }
  }
  window.addEventListener('focus', refresh);
  window.addEventListener('pageshow', refresh);
  window.addEventListener('online', refresh);
  document.addEventListener('visibilitychange', refresh);
  setInterval(refresh, 15000);
})();
