(function () {
  'use strict';
  function brand(node, size, keepText) {
    if (node.dataset.mishmaronBrand) return;
    node.dataset.mishmaronBrand = '1';
    var title = node.textContent.replace(/🛡️?/gu, '').trim();
    node.textContent = '';
    var img = document.createElement('img');
    img.src = '/__mishmaron_native_brand_v2.png';
    img.alt = 'משמרון';
    img.style.cssText = 'width:' + size + 'px;height:' + size + 'px;object-fit:contain;vertical-align:middle;border-radius:14px;';
    node.appendChild(img);
    if (keepText && title) node.appendChild(document.createTextNode(' ' + title));
  }
  document.querySelectorAll('.shield, .login-shield').forEach(function (node) { brand(node, 140, false); });
  document.querySelectorAll('.brand-mini b').forEach(function (node) { brand(node, 48, true); });
  // Restore only the existing user's selection; the server still verifies the worker session.
  try {
    var saved = localStorage.getItem('mishmaron_worker_id');
    var select = document.getElementById('workerSel');
    if (saved && select && Array.from(select.options).some(function (o) { return o.value === saved; })) {
      if (select.value !== saved) { select.value = saved; select.dispatchEvent(new Event('change')); }
      if (typeof window.openWorker === 'function') window.openWorker();
    }
  } catch (e) { /* A blocked storage setting must not prevent ordinary sign-in. */ }
})();
