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
  // Add only the requested registration link to existing original home screens.
  document.querySelectorAll('a[data-open-app]').forEach(function (node) { node.style.display = 'none'; });
  var splash = document.getElementById('splash');
  if (splash && !document.querySelector('a[data-native-signup]') && !document.querySelector('a[href="/signup"]')) {
    var signup = document.createElement('a');
    signup.dataset.nativeSignup = '1';
    signup.href = 'https://mishmaron-platform-production.up.railway.app/signup';
    signup.textContent = 'אין לי חשבון';
    signup.className = 'manager-entry';
    signup.style.cssText = 'display:block;text-align:left;margin:12px 0;';
    splash.parentNode.insertBefore(signup, splash);
  }
  // Remember an explicitly chosen area, never infer it from an old worker selection.
  try {
    var areaKey = 'mishmaron_area_v3';
    var homeRequested = new URLSearchParams(location.search).get('app_home') === '1';
    if (homeRequested) localStorage.removeItem(areaKey);
    var area = localStorage.getItem(areaKey);
    var saved = localStorage.getItem('mishmaron_worker_id');
    var select = document.getElementById('workerSel');
    if (select && !select.dataset.mishmaronRemember) {
      select.dataset.mishmaronRemember = '1';
      select.addEventListener('change', function () {
        try {
          if (select.value) localStorage.setItem('mishmaron_worker_id', select.value);
          else localStorage.removeItem('mishmaron_worker_id');
        } catch (e) {}
      });
    }
    if (typeof window.openWorker === 'function' && !window.openWorker.mishmaronWrapped) {
      var originalOpen = window.openWorker;
      window.openWorker = function () {
        try { localStorage.setItem(areaKey, 'worker'); } catch (e) {}
        return originalOpen.apply(this, arguments);
      };
      window.openWorker.mishmaronWrapped = true;
    }
    if (typeof window.backToSplash === 'function' && !window.backToSplash.mishmaronWrapped) {
      var originalBack = window.backToSplash;
      window.backToSplash = function () {
        try { localStorage.removeItem(areaKey); } catch (e) {}
        return originalBack.apply(this, arguments);
      };
      window.backToSplash.mishmaronWrapped = true;
    }
    document.querySelectorAll('a[href]').forEach(function (link) {
      if (new URL(link.href, location.href).pathname.indexOf('/admin') === 0 && !link.dataset.mishmaronArea) {
        link.dataset.mishmaronArea = '1';
        link.addEventListener('click', function () {
          try { localStorage.setItem(areaKey, 'admin'); } catch (e) {}
        });
      }
    });
    if (saved && select && !location.pathname.startsWith('/o/') && Array.from(select.options).some(function (o) { return o.value === saved; })) {
      if (select.value !== saved) { select.value = saved; select.dispatchEvent(new Event('change')); }
    }
    if (select && homeRequested && typeof window.backToSplash === 'function') window.backToSplash();
    // Opening the app always presents the organization's manager/worker home screen.
  } catch (e) { /* A blocked storage setting must not prevent ordinary sign-in. */ }
})();
