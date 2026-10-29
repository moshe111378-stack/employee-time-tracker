const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM, VirtualConsole} = require('jsdom');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(process.env.SYNC_FIXTURES, 'attendance-edit.html'), 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const valid = {cin_date:'26/10/2026', cin_time:'08:00', cout_date:'26/10/2026', cout_time:'19:02'};

function page() {
  const navigation = [];
  const console = new VirtualConsole();
  console.on('jsdomError', error => {
    if (error.message.includes('navigation')) navigation.push(error);
    else throw error;
  });
  const dom = new JSDOM(html, {url:'https://test.invalid/admin/event/1', runScripts:'outside-only', virtualConsole:console});
  const w = dom.window, d = w.document, form = d.querySelector('.manual-edit-form');
  const requests = [];
  w.fetch = async (url, options) => {requests.push({url, options}); return {ok:false, json:async()=>({ok:false,error:'השמירה נכשלה'})};};
  w.eval(fs.readFileSync(path.join(root, 'static/attendance-time.js'), 'utf8'));
  function fill(values, target=form) {
    Object.entries(values).forEach(([name, value]) => {
      target.elements[name].value = value;
      target.elements[name].dispatchEvent(new w.Event('input', {bubbles:true}));
    });
  }
  fill(valid);
  const values = (target=form) => Object.fromEntries(Object.keys(valid).map(name=>[name,target.elements[name].value]));
  const error = name => form.querySelector('[data-error-for="'+name+'"]').textContent;
  const status = () => form.querySelector('.attendance-save-status').textContent;
  return {dom,w,d,form,requests,fill,values,error,status,navigation};
}

async function run(name, fn) {
  const p = page();
  try {await fn(p); console.log('PASS '+name);} finally {p.dom.window.close();}
}

(async () => {
  await run('native submit blocks missing exit date and never guesses it', async p => {
    p.fill({cout_date:''});
    p.form.requestSubmit(); await flush();
    assert.equal(p.requests.length, 0);
    assert.equal(p.values().cout_date, '');
    assert.equal(p.error('cout_date'), 'חסר תאריך יציאה.');
    assert.equal(p.form.elements.cout_date.getAttribute('aria-invalid'), 'true');
    assert(p.form.elements.cout_date.required);
    assert(p.form.elements.cout_date.getAttribute('aria-describedby').includes('cout-date-error-1'));
    p.fill({cout_date:'26/10/2026'});
    assert.equal(p.error('cout_date'), '');
    assert(p.form.checkValidity());
  });
  await run('native submit blocks missing exit time and clearing both removes the error', async p => {
    p.fill({cout_time:''});p.form.requestSubmit(); await flush();
    assert.equal(p.requests.length, 0);
    assert.equal(p.error('cout_time'), 'חסרה שעת יציאה.');
    p.fill({cout_date:''});
    assert.equal(p.error('cout_time'), '');
    assert.equal(p.form.elements.cout_date.required, false);
    assert.equal(p.form.elements.cout_time.required, false);
    assert(p.form.checkValidity());
    p.form.requestSubmit();await flush();
    assert.equal(p.requests.length, 1);
    assert.equal(p.requests[0].options.body.get('cout_date'), '');
    assert.equal(p.requests[0].options.body.get('cout_time'), '');
  });
  await run('calendar selection clears the missing-date message', async p => {
    p.fill({cout_date:''});
    p.form.querySelector('[data-calendar-for="cout-date-1"]').click();
    assert.equal(p.values().cout_date, '', 'opening the calendar cannot choose a date');
    p.d.querySelector('[data-calendar-day="27"]').click();
    assert.equal(p.values().cout_date, '27/10/2026');
    assert.equal(p.error('cout_date'), '');
    assert(p.form.checkValidity());
  });
  await run('overnight date is sent exactly as selected', async p => {
    p.fill({cin_time:'22:00',cout_date:'27/10/2026',cout_time:'04:20'});
    p.form.requestSubmit();await flush();
    assert.equal(p.requests.length, 1);
    assert.equal(p.requests[0].options.body.get('cout_date'), '27/10/2026');
    assert.equal(p.requests[0].options.body.get('cout_time'), '04:20');
  });
  await run('JSON server errors retain every field and display inline errors', async p => {
    p.w.fetch = async () => ({ok:false,status:422,json:async()=>({ok:false,error:'בדוק תאריך',errors:{cout_date:'תאריך לא תקין'}})});
    p.form.requestSubmit();await flush();
    assert.deepEqual(p.values(), valid);
    assert.equal(p.error('cout_date'), 'תאריך לא תקין');
    assert.equal(p.status(), 'בדוק תאריך');
    assert.equal(p.navigation.length, 0);
    assert.equal(p.form.querySelector('button[type=submit]').disabled, false);
    p.fill({cout_date:'27/10/2026'});assert(p.form.checkValidity());
  });
  for (const [name, response] of [
    ['503 JSON', async()=>({ok:false,status:503,json:async()=>({ok:false,error:'השמירה נכשלה'})})],
    ['500 HTML', async()=>({ok:false,status:500,json:async()=>{throw new SyntaxError('HTML');}})],
    ['expired login redirect', async()=>({ok:true,redirected:true,json:async()=>({})})],
    ['offline', async()=>{throw new TypeError('offline');}],
    ['malformed success', async()=>({ok:true,json:async()=>({ok:true})})],
  ]) {
    await run(name+' preserves all edits and permits a deliberate retry', async p => {
      p.w.fetch = response;
      const second = p.form.cloneNode(true);p.form.after(second);
      p.fill({cin_time:'09:15'}, second);
      p.form.requestSubmit();await flush();
      assert.deepEqual(p.values(), valid);
      assert.equal(p.values(second).cin_time, '09:15');
      assert(p.status().includes('שמירה') || p.status().includes('השמירה'));
      assert.equal(p.navigation.length, 0);
      for (const control of p.form.elements) assert.equal(control.disabled, false);
      assert.equal(p.form.hasAttribute('aria-busy'), false);
      p.w.fetch=async(url,options)=>{p.requests.push({url,options});return {ok:false,json:async()=>({ok:false})};};
      p.form.requestSubmit();await flush();assert.equal(p.requests.length,1);
    });
  }
  await run('pending submission blocks duplicate taps and restores controls on timeout', async p => {
    let timeout, requests=0;
    p.w.setTimeout = (fn, ms) => {assert.equal(ms,20000);timeout=fn;return 1;};
    p.w.fetch = (url, options) => {requests++; return new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('timeout'))));};
    p.form.requestSubmit();
    assert.equal(p.form.querySelector('button[type=submit]').disabled, true);
    p.form.dispatchEvent(new p.w.Event('submit',{bubbles:true,cancelable:true}));
    assert.equal(requests,1);
    timeout();await flush();
    assert.deepEqual(p.values(),valid);
    assert.equal(p.form.querySelector('button[type=submit]').disabled,false);
    assert.match(p.status(),/לא התקבל אישור/);
  });
  await run('delegated validation covers a form replaced by live refresh', async p => {
    const next=p.form.cloneNode(true);p.form.replaceWith(next);
    p.fill({cout_date:''},next);next.requestSubmit();await flush();
    assert.equal(p.requests.length,0);
    assert.equal(next.elements.cout_date.validationMessage,'חסר תאריך יציאה.');
  });
  await run('failed edit is not overwritten by a later background refresh', async p => {
    p.w.setInterval=()=>1;
    p.w.eval(fs.readFileSync(path.join(root,'static/event-sync.js'),'utf8'));
    p.form.requestSubmit();await flush();
    const before=p.requests.length;
    p.form.closest('details').open=false;
    p.d.activeElement.blur();p.w.dispatchEvent(new p.w.Event('focus'));await flush();
    assert.equal(p.requests.length,before);
    assert.deepEqual(p.values(),valid);
  });
  await run('only a confirmed save navigates away', async p => {
    p.w.fetch=async()=>({ok:true,json:async()=>({ok:true,redirect:'/admin/event/1#report-1'})});
    p.form.requestSubmit();await flush();
    assert.equal(p.w.location.hash,'#report-1');
    assert.equal(p.navigation.length,1,'same-page success must reload saved totals');
  });
})().catch(error => {console.error(error);process.exitCode=1;});
