import os,sqlite3,uuid
from datetime import datetime
from functools import wraps
from flask import *
from werkzeug.security import generate_password_hash,check_password_hash
app=Flask(__name__);app.secret_key=os.getenv('SECRET_KEY','change-me')
DATA=os.getenv('DATA_DIR','/data');os.makedirs(DATA,exist_ok=True);UP=os.path.join(DATA,'uploads');os.makedirs(UP,exist_ok=True);DB=os.path.join(DATA,'hours.db')
def con(): c=sqlite3.connect(DB);c.row_factory=sqlite3.Row;return c
def init():
 c=con();c.executescript('CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY,name TEXT,user TEXT UNIQUE,pw TEXT);CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,name TEXT,date TEXT,active INTEGER DEFAULT 1);CREATE TABLE IF NOT EXISTS workers(id INTEGER PRIMARY KEY,name TEXT,phone TEXT);CREATE TABLE IF NOT EXISTS ew(event_id INTEGER,worker_id INTEGER,PRIMARY KEY(event_id,worker_id));CREATE TABLE IF NOT EXISTS att(id INTEGER PRIMARY KEY,event_id INTEGER,worker_id INTEGER,cin TEXT,cout TEXT,pinphoto TEXT,poutphoto TEXT,inlat TEXT,inlon TEXT,inacc TEXT,outlat TEXT,outlon TEXT,outacc TEXT);')
 if c.execute('select count(*) n from admins').fetchone()['n']==0:c.execute('insert into admins(name,user,pw) values(?,?,?)',('מנהל ראשי',os.getenv('ADMIN_USER','admin'),generate_password_hash(os.getenv('ADMIN_PASSWORD','change-this-password'))))
 c.commit();c.close()
init()
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
@app.route('/',methods=['GET','POST'])
def home():
 c=con();events=c.execute('select * from events where active=1 order by id desc').fetchall()
 eid=request.form.get('event_id') if request.method=='POST' else (request.args.get('event_id') or (str(events[0]['id']) if events else None))
 workers=c.execute('select w.* from workers w join ew on w.id=ew.worker_id where ew.event_id=? order by w.name',(eid,)).fetchall() if eid else []
 if request.method=='POST':
  wid=request.form.get('wid');w=c.execute('select * from workers where id=?',(wid,)).fetchone();openr=c.execute('select * from att where event_id=? and worker_id=? and cout is null order by id desc limit 1',(eid,wid)).fetchone()
  if not w:flash('עובד לא נמצא')
  elif not request.form.get('lat') or not request.form.get('lon'):flash('לא ניתן לדווח ללא מיקום נוכחי')
  elif not request.files.get('photo') or not request.files.get('photo').filename:flash('לא ניתן לדווח ללא תמונה')
  elif request.form['act']=='in' and openr:flash('כבר קיימת כניסה פתוחה')
  elif request.form['act']=='in':c.execute('insert into att(event_id,worker_id,cin,pinphoto,inlat,inlon,inacc) values(?,?,?,?,?,?,?)',(eid,wid,datetime.now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc')));c.commit();flash('הכניסה נרשמה בהצלחה')
  elif not openr:flash('אין כניסה פתוחה לסגירה')
  else:c.execute('update att set cout=?,poutphoto=?,outlat=?,outlon=?,outacc=? where id=?',(datetime.now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc'),openr['id']));c.commit();flash('היציאה נרשמה בהצלחה')
  c.close();return redirect('/?event_id='+str(eid))
 c.close();return render_template('home.html',events=events,workers=workers,selected_event=eid)
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
  wid=request.form.get('wid');w=c.execute('select * from workers where id=?',(wid,)).fetchone();openr=c.execute('select * from att where event_id=? and worker_id=? and cout is null order by id desc limit 1',(e,wid)).fetchone()
  if not w:flash('עובד לא נמצא')
  elif request.form['act']=='in' and openr:flash('כבר קיימת כניסה פתוחה')
  elif request.form['act']=='in':c.execute('insert into att(event_id,worker_id,cin,pinphoto,inlat,inlon,inacc) values(?,?,?,?,?,?,?)',(e,wid,datetime.now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc')));c.commit();flash('הכניסה נרשמה')
  elif not openr:flash('אין כניסה פתוחה לסגירה')
  else:c.execute('update att set cout=?,poutphoto=?,outlat=?,outlon=?,outacc=? where id=?',(datetime.now().isoformat(timespec='seconds'),photo(request.files.get('photo')),request.form.get('lat'),request.form.get('lon'),request.form.get('acc'),openr['id']));c.commit();flash('היציאה נרשמה')
  c.close();return redirect(f'/event/{e}')
 c.close();return render_template('event.html',event=ev,workers=ws)
@app.route('/admin/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  c=con();a=c.execute('select * from admins where user=?',(request.form['user'],)).fetchone();c.close()
  if a and check_password_hash(a['pw'],request.form['pw']):session['aid']=a['id'];return redirect('/admin')
  flash('פרטי כניסה שגויים')
 return render_template('login.html')
@app.get('/admin/logout')
def logout():session.clear();return redirect('/')
@app.get('/admin')
@adm
def admin():
 c=con();E=c.execute('select * from events order by id desc').fetchall();W=c.execute('select * from workers order by name').fetchall();A=c.execute('select id,name,user from admins').fetchall();c.close();return render_template('admin.html',events=E,workers=W,admins=A)
@app.post('/admin/add-event')
@adm
def ae():
 c=con();n=c.execute('select count(*) n from events').fetchone()['n']
 if n>=20:flash('מקסימום 20 אירועים')
 else:c.execute('insert into events(name,date) values(?,?)',(request.form['name'],request.form.get('date')));c.commit()
 c.close();return redirect('/admin')
@app.post('/admin/add-worker')
@adm
def aw():
 c=con();cur=c.execute('insert into workers(name,phone) values(?,?)',(request.form['name'],request.form.get('phone')));wid=cur.lastrowid
 # Auto-assign a new worker when there is exactly one active event, while keeping existing assignments intact
 es=c.execute('select id from events where active=1').fetchall()
 if len(es)==1 and c.execute('select count(*) n from ew where event_id=?',(es[0]['id'],)).fetchone()['n']<20:c.execute('insert or ignore into ew values(?,?)',(es[0]['id'],wid))
 c.commit();c.close();return redirect('/admin')
@app.post('/admin/worker/<int:w>/edit')
@adm
def edit_worker(w):
 c=con();c.execute('update workers set name=?,phone=? where id=?',(request.form['name'],request.form.get('phone'),w));c.commit();c.close();flash('פרטי העובד עודכנו');return redirect('/admin')
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
  n=c.execute('select count(*) n from ew where event_id=?',(e,)).fetchone()['n']
  if n>=20:flash('מקסימום 20 עובדים באירוע')
  else:c.execute('insert or ignore into ew values(?,?)',(e,request.form['wid']));c.commit()
 ev=c.execute('select * from events where id=?',(e,)).fetchone();W=c.execute('select * from workers order by name').fetchall();S=c.execute('select w.* from workers w join ew on w.id=ew.worker_id where ew.event_id=?',(e,)).fetchall();R=c.execute('select a.*,w.name from att a join workers w on w.id=a.worker_id where a.event_id=? order by a.id desc',(e,)).fetchall();c.close();return render_template('event_admin.html',event=ev,workers=W,assigned=S,rows=R)
@app.get('/uploads/<n>')
@adm
def uploads(n):return send_from_directory(UP,n)
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
