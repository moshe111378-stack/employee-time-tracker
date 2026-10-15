"""Explicit period totals entered by an administrator, separate from clock punches."""
import hashlib
import hmac
import json
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import abort, flash, redirect, render_template, request, session
from itsdangerous import BadData, URLSafeTimedSerializer


def hours_text(minutes):
    return f'{int(minutes)//60}:{int(minutes)%60:02d}'


def money_text(agorot):
    return '' if agorot is None else f'{Decimal(agorot)/100:.2f}'


def pay_agorot(minutes, rate):
    return None if rate is None else int((Decimal(minutes)*rate/60).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def manual_rows(connection, event_id=None, include_cancelled=False):
    where = [] if include_cancelled else ['h.cancelled_at is null']
    args = []
    if event_id is not None:
        where.append('h.event_id=?'); args.append(event_id)
    query = 'select h.*,e.name event_name,e.date event_date,e.end_date event_end_date from manual_hours h join events e on e.id=h.event_id'
    if where:
        query += ' where ' + ' and '.join(where)
    result = []
    for row in connection.execute(query+' order by h.id desc', args):
        item = dict(row)
        item['pay_agorot'] = pay_agorot(item['minutes'], item['rate_agorot'])
        result.append(item)
    return result


class FormError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status = status


def register_manual_hours(app, connect, admin_required, now, israel_tz):
    connection = connect()
    try:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS manual_hour_batches(
          token TEXT PRIMARY KEY, event_id INTEGER NOT NULL, admin_id INTEGER NOT NULL,
          payload_hash TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS manual_hours(
          id INTEGER PRIMARY KEY AUTOINCREMENT, batch_token TEXT NOT NULL,
          event_id INTEGER NOT NULL, worker_id INTEGER NOT NULL, worker_name TEXT NOT NULL,
          start_date TEXT NOT NULL, end_date TEXT NOT NULL,
          minutes INTEGER NOT NULL CHECK(minutes>0), rate_agorot INTEGER CHECK(rate_agorot>=0),
          note TEXT NOT NULL, admin_id INTEGER NOT NULL, admin_name TEXT NOT NULL, created_at TEXT NOT NULL,
          cancelled_at TEXT, cancelled_by INTEGER, cancelled_by_name TEXT,
          UNIQUE(batch_token,worker_id));
        CREATE INDEX IF NOT EXISTS idx_manual_hours_event ON manual_hours(event_id,start_date,end_date);
        ''')
        connection.commit()
    finally:
        connection.close()
    app.jinja_env.filters['hours_text'] = hours_text
    app.jinja_env.filters['money_text'] = money_text
    signer = URLSafeTimedSerializer(app.secret_key, salt='manual-hours-form-v1')

    def admin(connection):
        result = connection.execute('select id,name from admins where id=?', (session.get('aid'),)).fetchone()
        if not result:
            abort(403)
        return result

    def period(values):
        today = now().date()
        first = today-timedelta(days=(today.weekday()+1)%7)
        try:
            start = date.fromisoformat(values.get('start_date', first.isoformat()))
            end = date.fromisoformat(values.get('end_date', today.isoformat()))
        except (ValueError, TypeError):
            raise FormError('יש לבחור תאריך התחלה ותאריך סיום תקינים.')
        if start > end:
            raise FormError('תאריך הסיום חייב להיות באותו יום או אחרי תאריך ההתחלה.')
        if end > today:
            raise FormError('אפשר להוסיף רק שעות שכבר בוצעו, עד היום.')
        return start, end

    def snapshot(connection, event_id, start, end):
        workers = [dict(r) for r in connection.execute('select w.id,w.name,w.hourly_rate from workers w join ew on ew.worker_id=w.id where ew.event_id=? order by w.name', (event_id,))]
        punches = [dict(r) for r in connection.execute('select id,worker_id,cin,cout from att where event_id=? and substr(cin,1,10)<=? and (cout is null or substr(cout,1,10)>=?) order by id', (event_id,end.isoformat(),start.isoformat()))]
        manual = [dict(r) for r in connection.execute('select id,worker_id,start_date,end_date,minutes,rate_agorot,cancelled_at from manual_hours where event_id=? and start_date<=? and end_date>=? order by id', (event_id,end.isoformat(),start.isoformat()))]
        revision = hashlib.sha256(json.dumps([start.isoformat(),end.isoformat(),workers,punches,manual],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        existing = {w['id']: {'clocked':0,'manual':0,'open':0,'partial':False} for w in workers}
        lower, upper = datetime.combine(start,time()), datetime.combine(end+timedelta(days=1),time())
        for row in punches:
            if row['worker_id'] not in existing:
                continue
            totals = existing[row['worker_id']]
            if not row['cout']:
                totals['open'] += 1
                continue
            try:
                times = [datetime.fromisoformat(row[key]) for key in ('cin','cout')]
                times = [t.astimezone(israel_tz).replace(tzinfo=None) if t.tzinfo else t for t in times]
                totals['clocked'] += max(0,int((min(times[1],upper)-max(times[0],lower)).total_seconds()/60))
            except (ValueError, TypeError):
                pass
        for row in manual:
            if row['worker_id'] in existing and not row['cancelled_at']:
                totals = existing[row['worker_id']]
                totals['manual'] += row['minutes']
                totals['partial'] |= row['start_date'] < start.isoformat() or row['end_date'] > end.isoformat()
        return workers, existing, revision

    def csrf_valid():
        token = session.get('manual_hours_csrf','')
        return bool(token) and hmac.compare_digest(token,request.form.get('csrf',''))

    def parse_entries(workers, start, end):
        ids = request.form.getlist('worker_ids')
        known = {str(w['id']):w for w in workers}
        if len(ids)!=len(set(ids)) or not set(ids).issubset(known):
            raise FormError('רשימת השיוכים השתנתה. פתח מחדש את הוספת השעות ובדוק את העובדים.',409)
        entries = []
        for worker_id in ids:
            raw_hours = request.form.get('hours_'+worker_id,'').strip()
            raw_minutes = request.form.get('minutes_'+worker_id,'').strip()
            if not raw_hours and not raw_minutes:
                continue
            try:
                if (raw_hours and not raw_hours.isdecimal()) or (raw_minutes and not raw_minutes.isdecimal()):
                    raise ValueError()
                hours, minutes = int(raw_hours or 0), int(raw_minutes or 0)
            except ValueError:
                raise FormError('יש להזין שעות שלמות ודקות בין 0 ל־59; למשל 7 שעות ו־30 דקות.')
            if not 0 <= minutes <= 59:
                raise FormError('בשדה הדקות יש להזין מספר בין 0 ל־59.')
            total = hours*60+minutes
            if total == 0:
                continue
            if total > ((end-start).days+1)*24*60:
                raise FormError('סך השעות של עובד אינו יכול לעלות על מספר השעות בתקופה שנבחרה.')
            raw_rate = request.form.get('rate_'+worker_id,'').strip()
            rate = None
            if raw_rate:
                try:
                    value = Decimal(raw_rate)
                    if not value.is_finite() or value < 0 or value > 1000000 or value != value.quantize(Decimal('.01')):
                        raise InvalidOperation()
                    rate = int(value*100)
                except InvalidOperation:
                    raise FormError('יש להזין שכר שעתי תקין, עם עד שתי ספרות אחרי הנקודה.')
            worker = known[worker_id]
            entries.append((worker['id'],worker['name'],total,rate))
        if not entries:
            raise FormError('הזן שעות או דקות לפחות לעובד אחד. שורות ריקות אינן נשמרות.')
        return sorted(entries)

    @app.route('/admin/event/<int:e>/hours',methods=['GET','POST'])
    @admin_required
    def add_event_hours(e):
        connection = connect()
        error = None; status = 200
        values = request.form if request.method=='POST' else request.args
        try:
            actor = admin(connection)
            event = connection.execute('select * from events where id=?',(e,)).fetchone()
            if not event:
                abort(404)
            session.setdefault('manual_hours_csrf',secrets.token_urlsafe(32))
            try:
                start,end = period(values)
            except FormError as exc:
                start,end = period({}); error=str(exc); status=exc.status
            if request.method=='POST' and not csrf_valid():
                abort(403)
            form_token = signer.dumps({'event':e,'admin':actor['id'],'nonce':secrets.token_hex(16)})
            if request.method=='POST' and not error:
                try:
                    form_token = request.form.get('form_token','')
                    try:
                        signed = signer.loads(form_token,max_age=86400)
                    except BadData:
                        raise FormError('המסך פג תוקף. טען מחדש את רשימת העובדים לפני השמירה.')
                    if signed.get('event')!=e or signed.get('admin')!=actor['id']:
                        abort(403)
                    if request.form.get('only_missing')!='1':
                        raise FormError('יש לאשר שהוזנו רק שעות שטרם נרשמו.')
                    note = request.form.get('note','').strip()
                    if len(note)>500:
                        raise FormError('אפשר להזין הערה באורך של עד 500 תווים.')
                    connection.execute('BEGIN IMMEDIATE')
                    actor = admin(connection)
                    if not connection.execute('select id from events where id=?',(e,)).fetchone():
                        abort(404)
                    workers,existing,current_revision = snapshot(connection,e,start,end)
                    entries = parse_entries(workers,start,end)
                    digest = hashlib.sha256(json.dumps([e,start.isoformat(),end.isoformat(),note,entries],ensure_ascii=False).encode()).hexdigest()
                    saved = connection.execute('select payload_hash from manual_hour_batches where token=?',(form_token,)).fetchone()
                    if saved:
                        if saved['payload_hash']!=digest:
                            raise FormError('טופס זה כבר נשמר. פתח הוספת שעות חדשה עבור דיווח נוסף.',409)
                        connection.rollback(); flash('השעות כבר נשמרו. לא נוספו שעות כפולות.')
                        return redirect(f'/admin/event/{e}#manualHours')
                    if not hmac.compare_digest(current_revision,request.form.get('revision','')):
                        raise FormError('הדיווחים או השיוכים השתנו מאז פתיחת המסך. הסכומים עודכנו; בדוק שוב את השעות החסרות ואשר שמירה.',409)
                    created = now().isoformat(timespec='seconds')
                    connection.execute('insert into manual_hour_batches values(?,?,?,?,?)',(form_token,e,actor['id'],digest,created))
                    connection.executemany('insert into manual_hours(batch_token,event_id,worker_id,worker_name,start_date,end_date,minutes,rate_agorot,note,admin_id,admin_name,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?)',
                        [(form_token,e,wid,name,start.isoformat(),end.isoformat(),minutes,rate,note,actor['id'],actor['name'],created) for wid,name,minutes,rate in entries])
                    connection.commit()
                    flash(f'נוספו שעות ל־{len(entries)} עובדים. השעות נכללות בסיכום האירוע ובדוחות.')
                    return redirect(f'/admin/event/{e}#manualHours')
                except FormError as exc:
                    connection.rollback(); error=str(exc); status=exc.status
                    form_token = signer.dumps({'event':e,'admin':actor['id'],'nonce':secrets.token_hex(16)})
            workers,existing,revision = snapshot(connection,e,start,end)
            return render_template('manual_hours_form.html',event=event,workers=workers,existing=existing,
                start_date=start.isoformat(),end_date=end.isoformat(),today=now().date().isoformat(),
                error=error,values=request.form if request.method=='POST' else {},form_token=form_token,
                csrf=session['manual_hours_csrf'],revision=revision,back_url=f'/admin/event/{e}'),status
        finally:
            connection.close()

    @app.post('/admin/event/<int:e>/hours/<int:h>/cancel')
    @admin_required
    def cancel_event_hours(e,h):
        connection = connect()
        try:
            actor = admin(connection)
            if not csrf_valid():
                abort(403)
            if not connection.execute('select id from manual_hours where id=? and event_id=?',(h,e)).fetchone():
                abort(404)
            connection.execute('update manual_hours set cancelled_at=?,cancelled_by=?,cancelled_by_name=? where id=? and event_id=? and cancelled_at is null',
                (now().isoformat(timespec='seconds'),actor['id'],actor['name'],h,e))
            connection.commit()
        finally:
            connection.close()
        flash('הזנת השעות בוטלה ואינה נכללת בסכומים. התיעוד נשמר בהיסטוריה.')
        return redirect(f'/admin/event/{e}#manualHours')
