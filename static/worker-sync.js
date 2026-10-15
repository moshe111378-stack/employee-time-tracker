(function () {
  'use strict';
  if (typeof ws === 'undefined' || typeof es === 'undefined') return;
  let requestNumber = 0, controller = null, sending = false, inFlight = false;
  let currentShift = null;
  const originalChange = ws.onchange;
  const originalOpen = window.openWorker;

  function setEvents(events, oldEvent, openShift) {
    const list = events.slice();
    if (openShift && !list.some(e => String(e.id) === String(openShift.event_id))) {
      list.push({id: openShift.event_id, name: openShift.event_name + ' — משמרת פתוחה'});
    }
    const before = Array.from(es.options).map(o => [o.value, o.text]);
    const after = list.map(e => [String(e.id), e.name]);
    if (JSON.stringify(before) !== JSON.stringify(after)) {
      es.replaceChildren();
      list.forEach(e => es.add(new Option(e.name, String(e.id))));
    }
    if (list.some(e => String(e.id) === oldEvent)) es.value = oldEvent;
    else if (oldEvent && list.length) {
      es.add(new Option('השיוך השתנה — בחר אירוע', ''), 0);
      es.value = '';
    } else if (list.length) es.value = String(list[0].id);
    wrap.style.display = es.options.length > 1 ? 'block' : 'none';
    const selected = es.options[es.selectedIndex];
    box.replaceChildren();
    const title = document.createElement('b');
    title.textContent = selected && selected.value ? '✅ אירוע נבחר' : list.length ? '📅 בחר אירוע מהרשימה' : '❌ העובד לא משויך לאירוע';
    box.append(title);
    if (selected && selected.value) box.append(document.createElement('br'), document.createTextNode(selected.text));
    if (list.length > 1) {
      const hint = document.createElement('p');
      hint.className = 'muted';
      hint.textContent = 'משויכים אליך ' + list.length + ' אירועים. בחר את האירוע הרצוי ברשימה שמעל.';
      box.append(hint);
    }
  }

  async function refreshWorkerState(force) {
    if (!force && (sending || inFlight || document.hidden || navigator.onLine === false)) return false;
    if (controller) controller.abort();
    controller = new AbortController();
    const activeController = controller, number = ++requestNumber, workerId = ws.value;
    const timeout = setTimeout(() => activeController.abort(), 10000);
    inFlight = true;
    try {
      const response = await fetch('/worker-state?worker_id=' + encodeURIComponent(workerId), {
        credentials: 'same-origin', cache: 'no-store', signal: activeController.signal,
        headers: {'Accept': 'application/json'}
      });
      if (!response.ok) throw new Error('לא ניתן לעדכן את האירועים כרגע. נסה שוב.');
      const state = await response.json();
      if (number !== requestNumber || workerId !== ws.value) return false;
      const oldEvent = es.value;
      const currentWorkers = Array.from(ws.options).slice(1).map(o => [o.value, o.text]);
      const nextWorkers = state.workers.map(w => [String(w.id), w.name]);
      if (JSON.stringify(currentWorkers) !== JSON.stringify(nextWorkers)) {
        ws.replaceChildren(new Option('בחר את השם שלך', ''));
        state.workers.forEach(w => ws.add(new Option(w.name, String(w.id))));
        ws.value = workerId;
      }
      if (!state.worker_id || String(state.worker_id) !== workerId) {
        es.replaceChildren(); wrap.style.display = 'none';
        document.getElementById('rateWrap').style.display = 'none';
        box.textContent = workerId ? 'העובד אינו זמין ברשימה. פנה למנהל.' : 'בחר את השם שלך.';
        delete openShifts[workerId]; currentShift = null; renderTimer();
        return true;
      }
      // Keep the existing selection handler's source fresh without replacing forms/photos.
      for (let i = assignments.length - 1; i >= 0; i--) if (assignments[i].wid === workerId) assignments.splice(i, 1);
      state.events.forEach(e => assignments.push({wid: workerId, eid: String(e.id), event: e.name}));
      rates[workerId] = state.hourly_rate;
      if (state.hourly_rate !== null) {
        const content = document.getElementById('rateContent');
        const text = '₪' + Number(state.hourly_rate).toFixed(2) + ' לשעה · נעול לשינוי עובד';
        if (content.textContent !== text) content.textContent = text;
      }
      currentShift = state.open_shift;
      if (currentShift) openShifts[workerId] = currentShift.cin;
      else delete openShifts[workerId];
      renderTimer();
      setEvents(state.events, oldEvent, currentShift);
      return true;
    } catch (error) {
      if (force && error.name !== 'AbortError') throw error;
      if (force) throw new Error('החיבור לאתר התעכב. נסה שוב לפני הדיווח.');
      return false;
    } finally {
      clearTimeout(timeout);
      if (number === requestNumber) inFlight = false;
    }
  }

  ws.onchange = function () {
    originalChange.call(ws);
    currentShift = null;
    refreshWorkerState(true).catch(() => {});
  };
  window.openWorker = function () {
    originalOpen();
    refreshWorkerState(true).catch(() => {});
  };

  window.sendPunch = async function (action) {
    if (sending) return;
    if (!ws.value) { gps.textContent = '❌ בחר את השם שלך'; return; }
    if (localStorage.getItem('mishmaron_verified_worker') !== ws.value) {
      document.getElementById('deviceVerifyOverlay').classList.add('open'); return;
    }
    const buttons = Array.from(document.querySelectorAll('#workerScreen .actions button'));
    sending = true; buttons.forEach(b => b.disabled = true); ws.disabled = es.disabled = true;
    try {
      if (!await refreshWorkerState(true)) throw new Error('בחירת העובד השתנתה. נסה שוב.');
      if (!ws.value || !es.value) throw new Error('בחר שם ואירוע עדכני לפני הדיווח.');
      const hourly = document.getElementById('hourlyRate');
      if (hourly && (!hourly.value || Number(hourly.value) <= 0)) throw new Error('יש להזין שכר לשעה בפעם הראשונה');
      if (!photo.files.length) throw new Error('יש לצלם תמונה לפני הדיווח');
      if (!navigator.geolocation) throw new Error('אין תמיכה במיקום');
      const workerId = ws.value;
      const eventId = action === 'out' && currentShift ? String(currentShift.event_id) : es.value;
      gps.textContent = '📍 קולט מיקום נוכחי...';
      const position = await new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve,
        () => reject(new Error('יש לאשר גישה למיקום הנוכחי')), {enableHighAccuracy:true, maximumAge:0, timeout:15000}));
      const fd = new FormData();
      fd.append('wid', workerId); fd.append('act', action);
      fd.append('lat', position.coords.latitude); fd.append('lon', position.coords.longitude);
      fd.append('acc', Math.round(position.coords.accuracy)); fd.append('photo', photo.files[0]);
      if (hourly) fd.append('hourly_rate', hourly.value);
      const response = await fetch('/event/' + eventId, {method:'POST', body:fd, credentials:'same-origin', headers:{'X-Requested-With':'fetch'}});
      const result = await response.json();
      if (!response.ok || result.ok === false) throw new Error(result.error || 'הדיווח לא נשלח');
      if (result.type === 'in') openShifts[workerId] = new Date().toISOString();
      else delete openShifts[workerId];
      renderTimer(); showSuccessModal(result); photo.value = '';
      gps.textContent = '📍 המיקום ייקלט מחדש בזמן הדיווח הבא.';
      await refreshWorkerState(true).catch(() => {});
    } catch (error) {
      if ((error.message || '').includes('כבר קיימת כניסה פעילה')) showAlreadyWorkingModal();
      else if ((error.message || '').includes('אין כניסה פעילה')) showNotWorkingModal();
      else gps.textContent = '❌ ' + (error.message || 'הדיווח לא נשלח. בדוק את החיבור.');
    } finally {
      sending = false; buttons.forEach(b => b.disabled = false); ws.disabled = es.disabled = false;
    }
  };

  function resume() { if (!document.hidden) refreshWorkerState(false); }
  window.addEventListener('pageshow', resume);
  window.addEventListener('focus', resume);
  window.addEventListener('online', resume);
  document.addEventListener('visibilitychange', resume);
  setInterval(resume, 15000);
  refreshWorkerState(false);
})();
