(function () {
  'use strict';
  // A normal keyboard keeps / and : available for direct editing.
  // Format on blur only, so moving the caret or deleting digits stays natural.
  // Delegation also covers report forms replaced by the existing live refresh.
  document.addEventListener('focusout', function (event) {
    const input = event.target;
    if (!input.matches('.manual-edit-form input')) return;
    const value = input.value.trim();
    if (input.hasAttribute('data-attendance-date') && /^[0-9]{8}$/.test(value)) {
      input.value = value.slice(0, 2) + '/' + value.slice(2, 4) + '/' + value.slice(4);
    } else if (input.hasAttribute('data-attendance-time') && /^[0-9]{3,4}$/.test(value)) {
      input.value = value.slice(0, -2).padStart(2, '0') + ':' + value.slice(-2);
    }
  });
  document.addEventListener('input', function (event) {
    if (event.target.matches('.manual-edit-form input')) event.target.setCustomValidity('');
  });
  document.addEventListener('invalid', function (event) {
    const input = event.target;
    if (input.matches('[data-attendance-date]')) {
      input.setCustomValidity('בחר תאריך בלוח השנה או הקלד תאריך מלא, לדוגמה 22/10/2026.');
    } else if (input.matches('[data-attendance-time]')) {
      input.setCustomValidity('יש להקליד שעה, לדוגמה 19:02.');
    }
  }, true);

  // Render our own calendar so the app does not depend on a WebView date picker.
  const months = ['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר'];
  const pad = value => String(value).padStart(2, '0');
  let picker, target, trigger, selected, viewYear, viewMonth;
  function dateAt(year, month, day) {
    const date = new Date(0);
    date.setHours(12, 0, 0, 0);
    date.setFullYear(year, month, day);
    return date;
  }
  function parseDate(value) {
    const text = value.trim();
    const match = /^(\d{2})\/?(\d{2})\/?(\d{4})$/.exec(text);
    if (!match) return null;
    const date = dateAt(Number(match[3]), Number(match[2]) - 1, Number(match[1]));
    return date.getFullYear() === Number(match[3]) && date.getMonth() === Number(match[2]) - 1 && date.getDate() === Number(match[1]) ? date : null;
  }
  function closeCalendar() {
    picker.hidden = true;
    if (trigger && trigger.isConnected) trigger.focus();
  }
  function chooseDate(date) {
    target.value = pad(date.getDate()) + '/' + pad(date.getMonth() + 1) + '/' + String(date.getFullYear()).padStart(4, '0');
    target.setCustomValidity('');
    target.dispatchEvent(new Event('input', {bubbles:true}));
    target.dispatchEvent(new Event('change', {bubbles:true}));
    closeCalendar();
  }
  function renderMonth() {
    picker.querySelector('.attendance-calendar-month').textContent = months[viewMonth] + ' ' + viewYear;
    const days = picker.querySelector('.attendance-calendar-days');
    days.replaceChildren();
    for (let blank = 0; blank < dateAt(viewYear, viewMonth, 1).getDay(); blank++) days.append(document.createElement('span'));
    const total = dateAt(viewYear, viewMonth + 1, 0).getDate();
    const today = new Date();
    for (let day = 1; day <= total; day++) {
      const date = dateAt(viewYear, viewMonth, day), button = document.createElement('button');
      button.type = 'button';
      button.textContent = day;
      button.dataset.calendarDay = day;
      button.setAttribute('aria-label', day + ' ' + months[viewMonth] + ' ' + viewYear);
      button.setAttribute('aria-pressed', String(Boolean(selected && selected.getFullYear() === viewYear && selected.getMonth() === viewMonth && selected.getDate() === day)));
      if (today.getFullYear() === viewYear && today.getMonth() === viewMonth && today.getDate() === day) button.setAttribute('aria-current', 'date');
      button.addEventListener('click', () => chooseDate(date));
      days.append(button);
    }
  }
  function makeCalendar() {
    picker = document.createElement('div');
    picker.className = 'attendance-calendar';
    picker.hidden = true;
    picker.innerHTML = '<div class="attendance-calendar-card" role="dialog" aria-modal="true" aria-labelledby="attendance-calendar-title" tabindex="-1">' +
      '<h3 id="attendance-calendar-title">בחירת תאריך</h3>' +
      '<div class="attendance-calendar-nav"><button type="button" data-calendar-step="-1" aria-label="החודש הקודם">❯</button><strong class="attendance-calendar-month" aria-live="polite"></strong><button type="button" data-calendar-step="1" aria-label="החודש הבא">❮</button></div>' +
      '<div class="attendance-calendar-weekdays" aria-hidden="true"><span>א׳</span><span>ב׳</span><span>ג׳</span><span>ד׳</span><span>ה׳</span><span>ו׳</span><span>ש׳</span></div>' +
      '<div class="attendance-calendar-days"></div><div class="attendance-calendar-actions"><button type="button" data-calendar-today>היום</button><button type="button" data-calendar-close>ביטול</button></div></div>';
    document.body.append(picker);
    picker.querySelectorAll('[data-calendar-step]').forEach(button => button.addEventListener('click', () => {
      const month = dateAt(viewYear, viewMonth + Number(button.dataset.calendarStep), 1);
      if (month.getFullYear() < 1 || month.getFullYear() > 9999) return;
      viewYear = month.getFullYear(); viewMonth = month.getMonth(); renderMonth();
    }));
    picker.querySelector('[data-calendar-today]').addEventListener('click', () => chooseDate(new Date()));
    picker.querySelector('[data-calendar-close]').addEventListener('click', closeCalendar);
    picker.addEventListener('click', event => { if (event.target === picker) closeCalendar(); });
    picker.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); closeCalendar(); }
      if (event.key === 'Tab') {
        const buttons = picker.querySelectorAll('button'), first = buttons[0], last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    });
  }
  document.addEventListener('click', function (event) {
    const opener = event.target.closest('[data-calendar-for]');
    if (!opener) return;
    const input = document.getElementById(opener.dataset.calendarFor);
    if (!input) return;
    if (!picker) makeCalendar();
    target = input; trigger = opener; selected = parseDate(input.value);
    const entry = input.form.querySelector('[name="cin_date"]');
    const initial = selected || (entry && parseDate(entry.value)) || new Date();
    viewYear = initial.getFullYear(); viewMonth = initial.getMonth();
    renderMonth(); picker.hidden = false;
    const active = picker.querySelector('[aria-pressed="true"]') || picker.querySelector('[aria-current="date"]') || picker.querySelector('[data-calendar-day]');
    active.focus();
  });
})();
