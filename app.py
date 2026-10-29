import os,sqlite3,uuid,time,random,secrets,re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import *
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
def manager_form_time(form, prefix, required=False):
 # Keep accepting older pages while keyboard-friendly forms use separate fields.
 if prefix+'_date' not in form and prefix+'_time' not in form:
  value=form.get(prefix,'').strip()
  return parse_manager_time(value) if value or required else None
 day=form.get(prefix+'_date','').strip()
 clock=form.get(prefix+'_time','').strip()
 if not day and not clock and not required:return None
 if re.fullmatch(r'[0-9]{8}',day):day=day[:2]+'/'+day[2:4]+'/'+day[4:]
 if re.fullmatch(r'[0-9]{3,4}',clock):clock=clock[:-2]+':'+clock[-2:]
 if not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}',day) or not re.fullmatch(r'[0-9]{1,2}:[0-9]{2}',clock):
  raise ValueError('invalid date or time')
 date_value=datetime.strptime(day,'%d/%m/%Y').strftime('%Y-%m-%d')
 return parse_manager_time(date_value+'T'+clock.zfill(5))
def con(): c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def init():
 c=con();c.executescript('CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,name TEXT,user TEXT UNIQUE,pw TEXT);CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,name TEXT,date TEXT,active INTEGER DEFAULT 1);CREATE TABLE IF NOT EXISTS workers(id INTEGER PRIMARY KEY,name TEXT,phone TEXT);CREATE TABLE IF NOT EXISTS ew(event_id INTEGER,worker_id INTEGER,PRIMARY KEY(event_id,worker_id));CREATE TABLE IF NOT EXISTS att(id INTEGER PRIMARY KEY,event_id INTEGER,worker_id INTEGER,cin TEXT,cout TEXT,pinphoto TEXT,poutphoto TEXT,inlat TEXT,inlon TEXT,inacc TEXT,outlat TEXT,outlon TEXT,outacc TEXT);CREATE TABLE IF NOT EXISTS att_edits(id INTEGER PRIMARY KEY AUTOINCREMENT,attendance_id INTEGER NOT NULL,admin_id INTEGER,admin_name TEXT NOT NULL,old_cin TEXT,old_cout TEXT,new_cin TEXT NOT NULL,new_cout TEXT,edited_at TEXT NOT NULL);CREATE INDEX IF NOT EXISTS idx_att_edits_attendance ON att_edits(attendance_id,id);')
 if c.execute('select count(*) n from admins').fetchone()['n']==0:c.execute('insert into admins(name,user,pw) values(?,?,?)',('מנהל ראשי',os.getenv('ADMIN_USER','admin'),generate_password_hash(os.getenv('ADMIN_PASSWORD','change-this-password'))))
 c.commit();c.close()
init()
# Enrollment and saved assignments are never rewritten during process startup.
# Safe migration for existing databases
_m=con()
for _col in ['inlat','inlon','inacc','outlat','outlon','outacc']:
 try:_m.execute('alter table att add column '+_col+' TEXT')
 except sqlite3.OperationalError:pass
try:_m.execute('alter table workers add column hourly_rate REAL')
except sqlite3.OperationalError:pass
try:_m.execute('alter table workers add column device_code_hash TEXT')
except sqlite3.OperationalError:pass
try:_m.execute('alter table events add column end_date TEXT')
except sqlite3.OperationalError as exc:
 if 'duplicate column name' not in str(exc).lower():raise
_m.commit();_m.close()
def adm(f):
 @wraps(f)
 def w(*a,**k):return f(*a,**k) if session.get('aid') else redirect('/admin/login')
 return w
def photo(x):
 return save_attendance_photo(x, UP)
def dur(a,b):
 if not b:return 'פעיל'
 d=datetime.fromisoformat(b)-datetime.fromisoformat(a);m=int(d.total_seconds()/60);return f'{m//60}:{m%60:02d}'
app.jinja_env.globals['dur']=dur
from upload_security import save_attendance_photo, register_upload_security
register_upload_security(app)
from assignment_sync import register_sync, assignment_form_context, save_assignments
register_sync(app, con, ISRAEL_TZ)
from manual_hours import register_manual_hours, manual_rows, hours_text, money_text
register_manual_hours(app, con, adm, israel_now, ISRAEL_TZ)
from event_dates import event_period, validate_event_form
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
  wid=request.form.get('wid');w=c.execute('select * from workers where id=?',(wid,)).fetchone();rate=request.form.get('hourly_rate')
  if not session.get('worker_id') or str(session.get('worker_id'))!=str(wid):c.close();return jsonify(ok=False,error='המכשיר אינו מאומת לעובד הזה. יש לבצע אימות חד-פעמי.'),403 if request.headers.get('X-Requested-With')=='fetch' else redirect('/')
  if request.form.get('act')=='in' and not c.execute('select 1 from ew where event_id=? and worker_id=?',(e,wid)).fetchone():
   c.close();return jsonify(ok=False,error='השיוך לאירוע השתנה. יש לבחור אירוע עדכני.'),409
  if w and w['hourly_rate'] is None and rate:
   try:
    rv=float(rate)
    if rv>0:c.execute('update workers set hourly_rate=? where id=?',(rv,wid));c.commit();w=c.execute('select * from workers where id=?',(wid,)).fetchone()
   except ValueError:pass
  openr=c.execute('select * from att where worker_id=? and cout is null order by id desc limit 1',(wid,)).fetchone()
  if not w:flash('עובד לא נמצא')
  elif request.form['act']=='in' and openr:
   c.close();return jsonify(ok=False,error='כבר קיימת כניסה פעילה. יש לבצע יציאה לפני כניסה נוספת.'),409 if request.headers.get('X-Requested-With')=='fetch' else redirect('/')
  elif request.form['act']=='in':c.execute('insert into att(event_id,worker_id,cin,pinphoto,inlat,inlon,inacc) values(?,?,?,?,?,?,?)',(e,wid,israel_now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc')));c.commit()
  elif not openr:
   c.close();return jsonify(ok=False,error='אין כניסה פעילה. אתה לא במשמרת.'),409 if request.headers.get('X-Requested-With')=='fetch' else redirect('/')
  else:c.execute('update att set cout=?,poutphoto=?,outlat=?,outlon=?,outacc=? where id=?',(israel_now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc'),openr['id']));c.commit()
  result_type=request.form['act'];total='';
  if result_type=='out' and openr:
   end=israel_now();start=datetime.fromisoformat(openr['cin']);mins=max(0,int((end-start).total_seconds()/60));total=f'{mins//60}:{mins%60:02d}'
  pay='';hourly=w['hourly_rate'] if w else None
  if result_type=='out' and openr and hourly:pay=f'{(mins/60)*float(hourly):.2f}'
  c.close();return jsonify(ok=True,type=result_type,total=total,time=israel_now().strftime('%H:%M'),hourly=hourly,pay=pay) if request.headers.get('X-Requested-With')=='fetch' else redirect('/')
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
 session.setdefault('event_dates_csrf',secrets.token_urlsafe(32))
 c=con();E=c.execute('select * from events order by id desc').fetchall();W=c.execute('select * from workers order by name').fetchall();c.close();return render_template('admin_events.html',events=E,workers=W,event_dates_csrf=session['event_dates_csrf'])
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
 c=con()
 try:
  validate_event_form(c)
  try:start,end=event_period(request.form)
  except ValueError as exc:flash(str(exc));return redirect('/admin/events')
  if not request.form.get('name','').strip():flash('יש להזין שם אירוע');return redirect('/admin/events')
  c.execute('BEGIN IMMEDIATE')
  if c.execute('select count(*) n from events').fetchone()['n']>=100:flash('מקסימום 100 אירועים')
  else:
   cur=c.execute('insert into events(name,date,end_date) values(?,?,?)',(request.form['name'].strip(),start,end));eid=cur.lastrowid
   selected=request.form.getlist('worker_ids')[:50]
   c.executemany('insert or ignore into ew(event_id,worker_id) select ?,id from workers where id=?',[(eid,wid) for wid in selected])
   c.commit();flash('האירוע נוצר עם תאריך התחלה ותאריך סיום')
 finally:c.close()
 return redirect('/admin/events')
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
  try:save_assignments(c,e)
  finally:c.close()
  flash('שיוכי העובדים נשמרו. העובדים יראו את העדכון אוטומטית.')
  return redirect(f'/admin/event/{e}')
 if not c.execute('select id from events where id=?',(e,)).fetchone():c.close();abort(404)
 try:assignment_context=assignment_form_context(c,e)
 except BaseException:c.close();raise
 ev=c.execute('select * from events where id=?',(e,)).fetchone();W=c.execute('select * from workers order by name').fetchall();S=c.execute('select w.* from workers w join ew on w.id=ew.worker_id where ew.event_id=?',(e,)).fetchall();R=c.execute("select a.*,w.name,w.hourly_rate,(select x.admin_name from att_edits x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin,(select x.edited_at from att_edits x where x.attendance_id=a.id order by x.id desc limit 1) edited_at from att a join workers w on w.id=a.worker_id where a.event_id=? order by a.id desc",(e,)).fetchall();assigned_count=len(S);entered=len({x['worker_id'] for x in R});working=sum(1 for x in R if not x['cout']);finished=sum(1 for x in R if x['cout']);total_minutes=sum(max(0,int((datetime.fromisoformat(x['cout'])-datetime.fromisoformat(x['cin'])).total_seconds()/60)) for x in R if x['cout']);row_pay={};total_pay=0.0
 for x in R:
  if x['cout'] and x['hourly_rate']:
   mins=max(0,int((datetime.fromisoformat(x['cout'])-datetime.fromisoformat(x['cin'])).total_seconds()/60));pay=(mins/60)*float(x['hourly_rate']);row_pay[x['id']]=pay;total_pay+=pay
 manual_entries=manual_rows(c,e,include_cancelled=True)
 active_manual=[x for x in manual_entries if not x['cancelled_at']]
 total_minutes+=sum(x['minutes'] for x in active_manual)
 total_pay+=sum(x['pay_agorot'] or 0 for x in active_manual)/100
 session.setdefault('manual_hours_csrf',secrets.token_urlsafe(32))
 summary={'assigned':assigned_count,'entered':entered,'working':working,'finished':finished,'total':hours_text(total_minutes),'pay':f'{total_pay:.2f}','manual_count':len(active_manual),'unpriced_manual':sum(x['rate_agorot'] is None for x in active_manual)}
 c.close();return render_template('event_admin.html',event=ev,workers=W,assigned=S,rows=R,assigned_ids={str(x['id']) for x in S},summary=summary,row_pay=row_pay,manual_entries=manual_entries,manual_hours_csrf=session['manual_hours_csrf'],**assignment_context)
@app.post('/admin/event/<int:e>/report/<int:r>/edit')
@adm
def edit_attendance(e,r):
 def failure(message,status=422,errors=None):
  errors=errors or {}
  if request.headers.get('X-Requested-With')=='fetch':
   return jsonify(ok=False,error=message,errors=errors),status
  # Render the submitted values directly, without a redirect or a database read.
  # This also works when the database is temporarily unavailable.
  values={key:request.form.get(key,'') for key in ('cin_date','cin_time','cout_date','cout_time')}
  for prefix in ('cin','cout'):
   if prefix+'_date' not in request.form and prefix+'_time' not in request.form:
    legacy=request.form.get(prefix,'')
    values[prefix+'_date']=legacy[8:10]+'/'+legacy[5:7]+'/'+legacy[:4] if legacy else ''
    values[prefix+'_time']=legacy[11:] if legacy else ''
  return render_template('attendance_edit_error.html',event={'id':e},r={'id':r,'cin':None,'cout':None},
                         edit_values=values,edit_errors=errors,edit_message=message,
                         back_url=f'/admin/event/{e}#report-{r}'),status
 day=request.form.get('cout_date','').strip()
 clock=request.form.get('cout_time','').strip()
 if bool(day)!=bool(clock):
  key='cout_time' if day else 'cout_date'
  message='חסרה שעת יציאה.' if day else 'חסר תאריך יציאה.'
  return failure(message,errors={key:message})
 try:
  cin=manager_form_time(request.form,'cin',required=True)
  cout=manager_form_time(request.form,'cout')
 except ValueError:
  return failure('יש להזין תאריך ושעה תקינים. העריכה נשארה בטופס.')
 if cout and datetime.fromisoformat(cout)<=datetime.fromisoformat(cin):
  return failure('שעת היציאה חייבת להיות אחרי שעת הכניסה. למשמרת שחוצה חצות יש לבחור את תאריך היציאה המתאים.')
 c=None
 try:
  c=con()
  row=c.execute('select * from att where id=? and event_id=?',(r,e)).fetchone()
  if not row:return failure('הדיווח לא נמצא. העריכה נשארה בטופס.',404)
  if not cout:
   other=c.execute('select id from att where worker_id=? and cout is null and id<>? limit 1',(row['worker_id'],r)).fetchone()
   if other:return failure('לעובד כבר יש דיווח פתוח אחר. העריכה נשארה בטופס.',409)
  edited_at=israel_now().isoformat(timespec='seconds')
  c.execute('update att set cin=?,cout=? where id=? and event_id=?',(cin,cout,r,e))
  c.execute('insert into att_edits(attendance_id,admin_id,admin_name,old_cin,old_cout,new_cin,new_cout,edited_at) values(?,?,?,?,?,?,?,?)',(r,session.get('aid'),session.get('aname','מנהל'),row['cin'],row['cout'],cin,cout,edited_at))
  c.commit()
 except sqlite3.Error:
  if c:c.rollback()
  app.logger.exception('Attendance edit could not be saved')
  return failure('השמירה נכשלה. העריכה נשארה בטופס; אפשר לנסות שוב.',503)
 finally:
  if c:c.close()
 flash('השעות עודכנו ונשמרו עם סימון עריכת מנהל')
 if request.headers.get('X-Requested-With')=='fetch':
  return jsonify(ok=True,redirect=f'/admin/event/{e}#report-{r}')
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
def uploads(n):
 c=con()
 try:
  if not c.execute('select id from admins where id=?',(session.get('aid'),)).fetchone():abort(403)
  row=c.execute('select id,event_id,pinphoto from att where pinphoto=? or poutphoto=? order by id desc limit 1',(n,n)).fetchone()
 finally:c.close()
 # Keep image bytes available to embedded images and downloads. Navigating to
 # a photo (including older report links) opens a page with a way back.
 response=send_from_directory(UP,n)
 view=request.args.get('view')=='1' or (request.headers.get('Sec-Fetch-Dest')!='image' and request.accept_mimetypes['text/html']>0)
 if view and request.args.get('raw')!='1':
  response.close()
  title=('תמונת כניסה' if row['pinphoto']==n else 'תמונת יציאה') if row else 'תמונת דיווח'
  back=f'/admin/event/{row["event_id"]}#report-{row["id"]}' if row else '/admin/events'
  response=make_response(render_template('attendance_photo.html',photo_title=title,photo_url=url_for('uploads',n=n,raw=1),back_url=back))
 response.headers['Cache-Control']='no-store, no-cache, must-revalidate, max-age=0'
 response.headers['Pragma']='no-cache'
 response.vary.update(('Accept','Sec-Fetch-Dest'))
 return response
@app.get('/admin/reports')
@adm
def admin_reports():
 from period_reports import report_groups
 c=con()
 try:reports=report_groups(c)
 finally:c.close()
 return render_template('admin_reports.html',reports=reports,today=israel_now().date().isoformat())


@app.get('/health')
def health():return {'ok':True}

@app.post('/admin/event/<int:e>/edit')
@adm
def edit_event(e):
 c=con()
 try:
  validate_event_form(c)
  if not c.execute('select id from events where id=?',(e,)).fetchone():abort(404)
  try:start,end=event_period(request.form)
  except ValueError as exc:flash(str(exc));return redirect('/admin/events')
  if not request.form.get('name','').strip():flash('יש להזין שם אירוע');return redirect('/admin/events')
  c.execute('update events set name=?,date=?,end_date=? where id=?',(request.form['name'].strip(),start,end,e));c.commit()
 finally:c.close()
 flash('תאריכי האירוע עודכנו');return redirect('/admin/events')
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
 from period_reports import export_rows
 c=con()
 try:output=export_rows(c,e,dur)
 finally:c.close()
 return Response(output,mimetype='application/vnd.ms-excel; charset=utf-8',headers={'Content-Disposition':f'attachment; filename=event-{e}-report.xls'})
