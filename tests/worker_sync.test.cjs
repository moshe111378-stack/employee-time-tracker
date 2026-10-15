const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const root = path.resolve(__dirname, '..');
const fixture = process.env.SYNC_FIXTURES;
const flush = () => new Promise(resolve => setImmediate(resolve));

async function workerPage() {
  const intervals=[];
  const dom = new JSDOM(fs.readFileSync(path.join(fixture,'home.html'),'utf8'), {url:'https://test.invalid/',runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
    w.setInterval=fn=>{intervals.push(fn);return intervals.length;};w.clearInterval=()=>{};
    w.localStorage.setItem('mishmaron_worker_id','1');w.localStorage.setItem('mishmaron_verified_worker','1');
  }});
  const w=dom.window;
  await flush();
  let state={workers:[{id:1,name:'Worker One'},{id:2,name:'Worker Two'}],worker_id:1,hourly_rate:40,events:[{id:1,name:'Event One'},{id:2,name:'Event Two'}],open_shift:null};
  let fetches=0,posts=0,fail=false;
  w.fetch=async (url,options)=>{fetches++;if(fail)throw new Error('offline');if(options.method==='POST'){posts++;return {ok:true,json:async()=>({ok:true,type:'in',time:'12:00',hourly:40})};} return {ok:true,json:async()=>structuredClone(state)};};
  w.eval(fs.readFileSync(path.join(root,'static/worker-sync.js'),'utf8'));
  await flush();
  return {dom,w,intervals,setState:s=>state=s,state:()=>state,fetches:()=>fetches,posts:()=>posts,setFail:v=>fail=v};
}

(async()=>{
  const page=await workerPage(), {w}=page, doc=w.document;
  const ws=doc.getElementById('workerSel'),es=doc.getElementById('eventSel');
  es.value='2';
  const photo=doc.getElementById('photo');
  const file=new w.File(['fake test image'],'test.jpg',{type:'image/jpeg'});
  Object.defineProperty(photo,'files',{value:[file],configurable:true});
  page.setState({...page.state(),events:[...page.state().events,{id:4,name:'New project'}]});
  w.dispatchEvent(new w.Event('focus'));await flush();
  assert.equal(es.value,'2');assert.equal(es.options.length,3);assert.equal(photo.files[0],file);
  assert.match(doc.getElementById('eventBox').textContent,/3 אירועים/);
  console.log('PASS background update preserves selection and captured photo');

  page.setState({...page.state(),events:[{id:4,name:'New project'}]});
  w.dispatchEvent(new w.Event('focus'));await flush();
  assert.equal(es.value,'');assert.match(doc.getElementById('eventBox').textContent,/בחר אירוע/);
  console.log('PASS removing selected event requires deliberate selection');

  es.value='4';page.setFail(true);w.dispatchEvent(new w.Event('focus'));await flush();
  assert.equal(es.value,'4');assert.equal(photo.files[0],file);page.setFail(false);
  console.log('PASS temporary connection loss preserves report inputs');

  ws.value='2';ws.dispatchEvent(new w.Event('change'));await flush();
  page.setState({...page.state(),worker_id:2,hourly_rate:null,events:[]});
  ws.dispatchEvent(new w.Event('change'));await flush();
  const hourly=doc.getElementById('hourlyRate');hourly.value='55';
  w.dispatchEvent(new w.Event('focus'));await flush();assert.equal(doc.getElementById('hourlyRate').value,'55');
  console.log('PASS automatic refresh preserves unsubmitted hourly-rate input');

  // A delayed response for the previous worker must never overwrite the current choice.
  let finish;
  w.fetch=()=>new Promise(resolve=>finish=resolve);
  w.dispatchEvent(new w.Event('focus'));await flush();
  ws.value='1';
  finish({ok:true,json:async()=>({...page.state(),worker_id:2,events:[{id:9,name:'Wrong worker event'}]})});await flush();
  assert.equal(ws.value,'1');assert.ok(!Array.from(es.options).some(o=>o.value==='9'));
  console.log('PASS stale responses cannot cross worker selections');
  page.dom.window.close();

  const punch=await workerPage();
  Object.defineProperty(punch.w.document.getElementById('photo'),'files',{value:[new punch.w.File(['x'],'x.jpg')],configurable:true});
  Object.defineProperty(punch.w.navigator,'geolocation',{value:{getCurrentPosition:resolve=>resolve({coords:{latitude:1,longitude:2,accuracy:3}})}});
  await Promise.all([punch.w.sendPunch('in'),punch.w.sendPunch('in')]);
  assert.equal(punch.posts(),1);assert.equal(punch.w.document.getElementById('workerSel').disabled,false);
  console.log('PASS repeated taps produce one attendance request');
  punch.dom.window.close();

  const dom=new JSDOM(fs.readFileSync(path.join(fixture,'event.html'),'utf8'),{url:'https://test.invalid/admin/event/1',runScripts:'outside-only',pretendToBeVisual:true});
  const a=dom.window; a.setInterval=()=>1; let calls=0;
  const changed=a.document.documentElement.outerHTML.replace('<b>1</b><span>משויכים','<b>4</b><span>משויכים');
  a.fetch=async()=>{calls++;return {ok:true,redirected:false,text:async()=>changed};};
  a.eval(fs.readFileSync(path.join(root,'static/event-sync.js'),'utf8'));
  a.dispatchEvent(new a.Event('focus'));await flush();assert.match(a.document.getElementById('eventSummary').textContent,/4משויכים/);
  a.document.getElementById('assignmentEditor').open=true;const before=calls;
  a.dispatchEvent(new a.Event('focus'));await flush();assert.equal(calls,before);
  const checkbox=a.document.querySelector('input[name=worker_ids]');checkbox.checked=false;checkbox.dispatchEvent(new a.Event('change',{bubbles:true}));
  a.document.getElementById('assignmentEditor').open=false;a.dispatchEvent(new a.Event('focus'));await flush();assert.equal(calls,before);assert.equal(checkbox.checked,false);
  console.log('PASS manager summary refreshes without overwriting open or dirty assignment edits');
  dom.window.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
