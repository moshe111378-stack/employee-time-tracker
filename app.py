import os,sqlite3,uuid,time,random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import *
from attendance_admin import (ensure_audit_schema, attendance_edit_token, valid_edit_token, save_attendance_edit, attendance_pay, record_attendance, AttendanceRequestError)
import csv,io
from werkzeug.security import generate_password_hash,check_password_hash
app=Flask(__name__);app.secret_key=os.getenv('SECRET_KEY','change-me');app.permanent_session_lifetime=timedelta(days=365);app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,SESSION_COOKIE_SAMESITE='Lax')
DATA=os.getenv('DATA_DIR','/data');os.makedirs(DATA,exist_ok=True);UP=os.path.join(DATA,'uploads');os.makedirs(UP,exist_ok=True);DB=os.path.join(DATA,'hours.db')
ISRAEL_TZ=ZoneInfo('Asia/Jerusalem')
def israel_now(): return datetime.now(ISRAEL_TZ).replace(tzinfo=None)
def parse_manager_time(value):
 dt=datetime.strptime(value,'%Y-%m-%dT%H:%M')
 local=dt.replace(tzinfo=ISRAEL_TZ)
 if local.astimezone(timezone.utc).astimezone(ISRAEL_TZ).replace(tzinfo=None)!=dt:raise ValueError('invalid local time')
 return dt.isoformat(timespec='seconds')
def con(): c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def init():
 c=con();c.executescript('CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,name TEXT,user TEXT UNIQUE,pw TEXT);CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,name TEXT,date TEXT,active INTEGER DEFAULT 1);CREATE TABLE IF NOT EXISTS workers(id INTEGER PRIMARY KEY,name TEXT,phone TEXT);CREATE TABLE IF NOT EXISTS ew(event_id INTEGER,worker_id INTEGER,PRIMARY KEY(event_id,worker_id));CREATE TABLE IF NOT EXISTS att(id INTEGER PRIMARY KEY,event_id INTEGER,worker_id INTEGER,cin TEXT,cout TEXT,pinphoto TEXT,poutphoto TEXT,inlat TEXT,inlon TEXT,inacc TEXT,outlat TEXT,outlon TEXT,outacc TEXT);')
 ensure_audit_schema(c)
 if c.execute('select count(*) n from admins').fetchone()['n']==0:c.execute('insert into admins(name,user,pw) values(?,?,?)',('מנהל ראשי',os.getenv('ADMIN_USER','admin'),generate_password_hash(os.getenv('ADMIN_PASSWORD','change-this-password'))))
 c.commit();c.close()
init()
app.jinja_env.globals['attendance_edit_token']=attendance_edit_token
# One-time worker-device auth reset only; admin sessions/accounts are untouched
if os.getenv('WORKER_DEVICE_AUTH_RESET_V1')=='1':
 _r=con();_r.execute('update workers set device_code_hash=null');_r.commit();_r.close()
# One-time safe assignment: when exactly one active event exists, attach existing unassigned workers to it (up to 20)
_fix=con();_es=_fix.execute('select id from events where active=1').fetchall()
if len(_es)==1:
 _eid=_es[0]['id'];_count=_fix.execute('select count(*) n from ew where event_id=?',(_eid,)).fetchone()['n']
 _missing=_fix.execute('select id from workers where id not in (select worker_id from ew where event_id=?) order by id',(_eid,)).fetchall()
 for _w in _missing[:max(0,20-_count)]:_fix.execute('insert or ignore into ew values(?,?)',(_eid,_w['id']))
 _fix.commit()
_fix.close()
# Safe migration for existing databases
_m=con()
for _col in ['inlat','inlon','inacc','outlat','outlon','outacc']:
 try:_m.execute('alter table att add column '+_col+' TEXT')
 except sqlite3.OperationalError:pass
try:_m.execute('alter table workers add column hourly_rate REAL')
except sqlite3.OperationalError:pass
try:_m.execute('alter table workers add column device_code_hash TEXT')
except sqlite3.OperationalError:pass
_m.commit();_m.close()
def adm(f):
 @wraps(f)
 def w(*a,**k):return f(*a,**k) if session.get('aid') else redirect('/admin/login')
 return w
def photo(x):
 if not x or not x.filename:return None
 n=uuid.uuid4().hex+'.jpg';x.save(os.path.join(UP,n));return n
def dur(a,b):
 if not b:return 'פעיל'
 d=datetime.fromisoformat(b)-datetime.fromisoformat(a);m=int(d.total_seconds()/60);return f'{m//60}:{m%60:02d}'
app.jinja_env.globals['dur']=dur
@app.after_request
def no_cache_assets(r):
 if request.path.startswith('/static/'):
  r.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
  r.headers['Pragma']='no-cache'
 return r
@app.get('/')
def home():
 c=con()
 workers=c.execute('select id,name,hourly_rate from workers order by name').fetchall()
 assignments=c.execute('select ew.worker_id,ew.event_id,e.name event_name from ew join events e on e.id=ew.event_id where e.active=1 order by e.name').fetchall()
 open_shifts=c.execute('select worker_id,cin from att where cout is null order by id').fetchall();open_map={str(x["worker_id"]):x["cin"] for x in open_shifts}
 c.close()
 success=session.pop('attendance_success',None)
 return render_template('home.html',workers=workers,assignments=assignments,success=success,open_map=open_map)
@app.after_request
def no_cache(resp):
 if request.path.startswith('/static/') or request.path=='/':
  resp.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
  resp.headers['Pragma']='no-cache'
 return resp
@app.route('/event/<int:e>',methods=['GET','POST'])
def event(e):
 c=con();ev=c.execute('select * from events where id=? and active=1',(e,)).fetchone();ws=c.execute('select w.* from workers w join ew on w.id=ew.worker_id where ew.event_id=? order by w.name',(e,)).fetchall()
 if not ev:c.close();abort(404)
 if request.method=='POST':
  wid=request.form.get('wid')
  if not session.get('worker_id') or str(session.get('worker_id'))!=str(wid):
   c.close()
   message='המכשיר אינו מאומת לעובד הזה. יש לבצע אימות חד-פעמי.'
   if request.headers.get('X-Requested-With')=='fetch':return jsonify(ok=False,error=message),403
   flash(message);return redirect('/')
  try:
   result=record_attendance(c,e,wid,request.form.get('act'),israel_now,
    lambda:photo(request.files.get('photo')),
    (request.form.get('lat'),request.form.get('lon'),request.form.get('acc')),
    request.form.get('hourly_rate'))
  except AttendanceRequestError as error:
   if request.headers.get('X-Requested-With')=='fetch':return jsonify(ok=False,error=str(error)),error.status
   flash(str(error));return redirect('/')
  except sqlite3.OperationalError as error:
   if 'locked' not in str(error).lower() and 'busy' not in str(error).lower():raise
   message='הדיווח לא נשמר כי המערכת עסוקה. יש לנסות שוב בעוד רגע.'
   if request.headers.get('X-Requested-With')=='fetch':return jsonify(ok=False,error=message),503
   flash(message);return redirect('/')
  finally:c.close()
  return jsonify(result) if request.headers.get('X-Requested-With')=='fetch' else redirect('/')
 c.close();return render_template('event.html',event=ev,workers=ws)
@app.post('/worker-device/verify')
def worker_device_verify():
 wid=request.form.get('worker_id');code=request.form.get('code','');c=con();w=c.execute('select * from workers where id=?',(wid,)).fetchone()
 if not w or not w['device_code_hash'] or not check_password_hash(w['device_code_hash'],code):c.close();return jsonify(ok=False,error='קוד אימות שגוי'),401
 c.execute('update workers set device_code_hash=null where id=?',(wid,));c.commit();c.close();session['worker_id']=int(wid);session.permanent=True;return jsonify(ok=True)
@app.post('/admin/worker/<int:w>/new-device-code')
@adm
def new_device_code(w):
 code=f'{random.SystemRandom().randrange(100000,1000000)}';c=con();c.execute('update workers set device_code_hash=? where id=?',(generate_password_hash(code),w));c.commit();c.close();flash('קוד אימות חדש לעובד: '+code);return redirect('/admin/workers')

@app.route('/admin/login',methods=['GET','POST'])
def login():
 if request.method=='GET' and session.get('aid'):return redirect('/admin')
 if request.method=='POST':
  c=con();a=c.execute('select * from admins where user=?',(request.form['user'],)).fetchone();c.close()
  if a and check_password_hash(a['pw'],request.form['pw']):session.clear();session['aid']=a['id'];session['aname']=a['name'];session.permanent=request.form.get('remember')=='1';return redirect('/admin')
  flash('פרטי כניסה שגויים')
 return render_template('login.html')
@app.get('/admin/logout')
def logout():session.clear();return redirect('/')
@app.get('/admin')
@adm
def admin():
 c=con();E=c.execute('select * from events order by id desc').fetchall();W=c.execute('select * from workers order by name').fetchall();A=c.execute('select id,name,user from admins').fetchall();O=c.execute("select a.*,w.name,e.name event_name from att a join workers w on w.id=a.worker_id join events e on e.id=a.event_id where a.cout is null order by a.cin").fetchall();now=israel_now();active=[dict(x,minutes=max(0,int((now-datetime.fromisoformat(x['cin'])).total_seconds()/60))) for x in O];alerts=[x for x in active if x['minutes']>=480];c.close();return render_template('admin.html',events=E,workers=W,admins=A,active=active,alerts=alerts,admin_name=session.get('aname','מנהל'))
@app.get('/admin/events')
@adm
def admin_events():
 c=con();E=c.execute('select * from events order by id desc').fetchall();W=c.execute('select * from workers order by name').fetchall();c.close();return render_template('admin_events.html',events=E,workers=W)
@app.get('/admin/workers')
@adm
def admin_workers():
 c=con();W=c.execute('select * from workers order by name').fetchall();c.close();return render_template('admin_workers.html',workers=W)
@app.get('/admin/admins')
@adm
def admin_admins():
 c=con();A=c.execute('select id,name,user from admins').fetchall();c.close();return render_template('admin_admins.html',admins=A)
@app.post('/admin/add-event')
@adm
def ae():
 c=con();n=c.execute('select count(*) n from events').fetchone()['n']
 if n>=100:flash('מקסימום 100 אירועים')
 else:
  cur=c.execute('insert into events(name,date) values(?,?)',(request.form['name'],request.form.get('date')));eid=cur.lastrowid
  for wid in request.form.getlist('worker_ids')[:50]:c.execute('insert or ignore into ew values(?,?)',(eid,wid))
  c.commit()
 c.close();return redirect('/admin')
@app.post('/admin/add-worker')
@adm
def aw():
 c=con();n=c.execute('select count(*) n from workers').fetchone()['n']
 if n>=500:flash('מקסימום 500 עובדים')
 else:
  code=f'{random.SystemRandom().randrange(100000,1000000)}';c.execute('insert into workers(name,phone,device_code_hash) values(?,?,?)',(request.form['name'],request.form.get('phone'),generate_password_hash(code)));c.commit();flash('העובד נוסף. קוד האימות החד-פעמי שלו: '+code)
 c.close();return redirect('/admin')
@app.post('/admin/worker/<int:w>/edit')
@adm
def edit_worker(w):
 c=con();rate=request.form.get('hourly_rate');c.execute('update workers set name=?,phone=?,hourly_rate=? where id=?',(request.form['name'],request.form.get('phone'),float(rate) if rate else None,w));c.commit();c.close();flash('פרטי העובד עודכנו');return redirect('/admin')
@app.post('/admin/worker/<int:w>/delete')
@adm
def delete_worker(w):
 c=con();c.execute('delete from ew where worker_id=?',(w,));c.execute('delete from workers where id=?',(w,));c.commit();c.close();flash('העובד נמחק');return redirect('/admin')
@app.post('/admin/add-admin')
@adm
def aa():
 c=con();n=c.execute('select count(*) n from admins').fetchone()['n']
 if n>=10:flash('מקסימום 10 מנהלים')
 else:c.execute('insert into admins(name,user,pw) values(?,?,?)',(request.form['name'],request.form['user'],generate_password_hash(request.form['pw'])));c.commit()
 c.close();return redirect('/admin')
@app.route('/admin/event/<int:e>',methods=['GET','POST'])
@adm
def ea(e):
 c=con()
 if request.method=='POST':
  selected=request.form.getlist('worker_ids')
  c.execute('delete from ew where event_id=?',(e,))
  for wid in selected[:50]:c.execute('insert or ignore into ew values(?,?)',(e,wid))
  c.commit();flash('שיוכי העובדים נשמרו')
 ev=c.execute('select * from events where id=?',(e,)).fetchone();W=c.execute('select * from workers order by name').fetchall();S=c.execute('select w.* from workers w join ew on w.id=ew.worker_id where ew.event_id=?',(e,)).fetchall();R=c.execute("select a.*,w.name,w.hourly_rate,(select x.admin_name from attendance_edit_history x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin,(select x.edited_at from attendance_edit_history x where x.attendance_id=a.id order by x.id desc limit 1) edited_at from att a join workers w on w.id=a.worker_id where a.event_id=? order by a.id desc",(e,)).fetchall();assigned_count=len(S);entered=len({x['worker_id'] for x in R});working=sum(1 for x in R if not x['cout']);finished=sum(1 for x in R if x['cout']);total_minutes=sum(max(0,int((datetime.fromisoformat(x['cout'])-datetime.fromisoformat(x['cin'])).total_seconds()/60)) for x in R if x['cout']);row_pay={};total_pay=0.0
 for x in R:
  if x['cout'] and x['hourly_rate']:
   mins=max(0,int((datetime.fromisoformat(x['cout'])-datetime.fromisoformat(x['cin'])).total_seconds()/60));pay=(mins/60)*float(x['hourly_rate']);row_pay[x['id']]=pay;total_pay+=pay
 summary={'assigned':assigned_count,'entered':entered,'working':working,'finished':finished,'total':f"{total_minutes//60}:{total_minutes%60:02d}",'pay':f'{total_pay:.2f}'};c.close();return render_template('event_admin.html',event=ev,workers=W,assigned=S,rows=R,assigned_ids={str(x['id']) for x in S},summary=summary,row_pay=row_pay)
@app.post('/admin/event/<int:e>/report/<int:r>/edit')
@adm
def edit_attendance(e,r):
 if not valid_edit_token(request.form.get('edit_token','')):abort(400)
 c=con()
 try:
  changed=save_attendance_edit(c,e,r,session.get('aid'),request.form.get('cin',''),request.form.get('cout',''))
 except PermissionError:abort(403)
 except LookupError:abort(404)
 except ValueError as error:flash(str(error))
 else:flash('השעות עודכנו ונשמרו עם סימון עריכת מנהל' if changed else 'לא בוצע שינוי בשעות')
 finally:c.close()
 return redirect(f'/admin/event/{e}')

@app.post('/admin/event/<int:e>/report/<int:r>/delete')
@adm
def delete_report(e,r):
 c=con();row=c.execute('select pinphoto,poutphoto from att where id=? and event_id=?',(r,e)).fetchone()
 if row:
  c.execute('delete from att where id=? and event_id=?',(r,e));c.commit()
  for fn in (row['pinphoto'],row['poutphoto']):
   if fn:
    try:os.remove(os.path.join(UP,fn))
    except OSError:pass
 c.close();flash('הדוח נמחק');return redirect(f'/admin/event/{e}')
@app.get('/uploads/<n>')
@adm
def uploads(n):return send_from_directory(UP,n)
@app.get('/admin/reports')
@adm
def admin_reports():
 c=con();rows=c.execute("""select a.*,w.name worker_name,w.hourly_rate,e.name event_name,e.date event_date,(select x.admin_name from attendance_edit_history x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin,(select x.edited_at from attendance_edit_history x where x.attendance_id=a.id order by x.id desc limit 1) edited_at from att a join workers w on w.id=a.worker_id join events e on e.id=a.event_id where a.cout is not null order by e.date desc,a.id desc""").fetchall();events={}
 for x in rows:
  try:mins=max(0,int((datetime.fromisoformat(x['cout'])-datetime.fromisoformat(x['cin'])).total_seconds()/60))
  except:mins=0
  pay=(mins/60)*float(x['hourly_rate'] or 0);eid=x['event_id']
  if eid not in events:events[eid]={'id':eid,'name':x['event_name'],'date':x['event_date'],'minutes':0,'pay':0.0,'workers':set(),'rows':[]}
  ev=events[eid];ev['minutes']+=mins;ev['pay']+=pay;ev['workers'].add(x['worker_id']);ev['rows'].append({'worker':x['worker_name'],'cin':x['cin'],'cout':x['cout'],'minutes':mins,'rate':float(x['hourly_rate'] or 0),'pay':pay,'edit_admin':x['edit_admin'],'edited_at':x['edited_at']})
 out=[]
 for ev in events.values():ev['worker_count']=len(ev['workers']);ev['hours']=f"{ev['minutes']//60}:{ev['minutes']%60:02d}";ev['pay_text']=f"{ev['pay']:.2f}";out.append(ev)
 c.close();return render_template('admin_reports.html',reports=out)


@app.get('/health')
def health():return {'ok':True}

@app.post('/admin/event/<int:e>/edit')
@adm
def edit_event(e):
 c=con();c.execute('update events set name=?,date=? where id=?',(request.form['name'],request.form.get('date'),e));c.commit();c.close();flash('האירוע עודכן');return redirect('/admin')
@app.post('/admin/event/<int:e>/delete')
@adm
def delete_event(e):
 c=con();c.execute('delete from ew where event_id=?',(e,));c.execute('delete from events where id=?',(e,));c.commit();c.close();flash('האירוע נמחק');return redirect('/admin')

@app.post('/admin/event/<int:e>/reset-workers')
@adm
def reset_event_workers(e):
 c=con();c.execute('delete from ew where event_id=?',(e,));c.commit();c.close();flash('כל שיוכי העובדים לאירוע אופסו. העובדים עצמם נשארו במערכת.');return redirect(f'/admin/event/{e}')

@app.get('/admin/event/<int:e>/export.csv')
@adm
def export_event(e):
 c=con();rows=c.execute('select a.*,w.name,w.hourly_rate,(select x.admin_name from attendance_edit_history x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin from att a join workers w on w.id=a.worker_id where a.event_id=? order by a.id',(e,)).fetchall();c.close()
 out=io.StringIO();out.write('\ufeff');writer=csv.writer(out,delimiter='\t')
 writer.writerow(['עובד','כניסה','יציאה','סהכ שעות','מיקום כניסה','מיקום יציאה','נערך על ידי מנהל','שכר לשעה','סהכ לתשלום'])
 for r in rows:
  writer.writerow([r['name'],r['cin'],r['cout'] or '',dur(r['cin'],r['cout']),f"{r['inlat'] or ''},{r['inlon'] or ''}",f"{r['outlat'] or ''},{r['outlon'] or ''}",'נערך על ידי מנהל - '+r['edit_admin'] if r['edit_admin'] else '',f"{float(r['hourly_rate']):.2f}" if r['hourly_rate'] is not None else '',attendance_pay(r)])
 return Response(out.getvalue(),mimetype='application/vnd.ms-excel; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=event-{e}-report.xls'})
