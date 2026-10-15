"""Event assignment editing and live state, without attendance/data migrations."""
import hashlib
import hmac
import secrets
from datetime import datetime
from flask import abort, jsonify, request, session


def revision(worker_ids):
    return hashlib.sha256(','.join(map(str, sorted(map(int, worker_ids)))).encode()).hexdigest()


def assignment_form_context(connection, event_id):
    if not connection.execute('select id from admins where id=?', (session.get('aid'),)).fetchone():
        abort(403)
    session.setdefault('assignment_csrf', secrets.token_urlsafe(32))
    ids = [r['worker_id'] for r in connection.execute('select worker_id from ew where event_id=?', (event_id,))]
    return {'assignment_csrf': session['assignment_csrf'], 'assignment_revision': revision(ids)}


def save_assignments(connection, event_id):
    """Validate before changing anything; reject stale forms atomically."""
    try:
        connection.execute('BEGIN IMMEDIATE')
        if not connection.execute('select id from admins where id=?', (session.get('aid'),)).fetchone():
            abort(403)
        if not connection.execute('select id from events where id=?', (event_id,)).fetchone():
            abort(404)
        token = session.get('assignment_csrf', '')
        if not token or not hmac.compare_digest(token, request.form.get('assignment_csrf', '')):
            abort(403, description='יש לפתוח מחדש את מסך האירוע ולנסות שוב.')
        if request.form.get('assignments_present') != '1':
            abort(400, description='לא התקבלה רשימת שיוכים. לא נשמרו שינויים.')
        raw = request.form.getlist('worker_ids')
        if len(raw) > 50:
            abort(400, description='ניתן לשייך עד 50 עובדים לאירוע.')
        try:
            selected = {int(w) for w in raw}
        except (ValueError, TypeError):
            abort(400, description='רשימת העובדים אינה תקינה.')
        existing_workers = {r['id'] for r in connection.execute('select id from workers')}
        if not selected.issubset(existing_workers):
            abort(400, description='אחד העובדים אינו קיים. רענן את הרשימה.')
        current = {r['worker_id'] for r in connection.execute('select worker_id from ew where event_id=?', (event_id,))}
        if not hmac.compare_digest(revision(current), request.form.get('assignment_revision', '')):
            abort(409, description='השיוכים עודכנו בחלון אחר. חזור לאירוע ופתח מחדש את עריכת השיוכים.')
        connection.executemany('delete from ew where event_id=? and worker_id=?', [(event_id, w) for w in current - selected])
        connection.executemany('insert into ew(event_id,worker_id) values(?,?)', [(event_id, w) for w in selected - current])
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def register_sync(app, connect, israel_tz):
    @app.get('/worker-state')
    def worker_state():
        # Same fields already rendered by the public worker page;
        # return attendance/rate only for the selected worker, never phones/codes.
        worker_id = request.args.get('worker_id', type=int)
        connection = connect()
        try:
            connection.execute('BEGIN')
            workers = [dict(r) for r in connection.execute('select id,name from workers order by name')]
            worker = connection.execute('select id,hourly_rate from workers where id=?', (worker_id,)).fetchone()
            events = [dict(r) for r in connection.execute('select e.id,e.name from ew join events e on e.id=ew.event_id where ew.worker_id=? and e.active=1 order by e.name', (worker_id,))]
            opened = connection.execute('select a.cin,e.id event_id,e.name event_name from att a join events e on e.id=a.event_id where a.worker_id=? and a.cout is null order by a.id desc limit 1', (worker_id,)).fetchone()
            shift = dict(opened) if opened else None
            if shift:
                started = datetime.fromisoformat(shift['cin'])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=israel_tz)
                shift['cin'] = started.isoformat()
            return jsonify(workers=workers, worker_id=worker['id'] if worker else None,
                           hourly_rate=worker['hourly_rate'] if worker else None,
                           events=events, open_shift=shift)
        finally:
            connection.close()

    @app.context_processor
    def back_navigation():
        path = request.path
        if path.startswith('/admin/event/'):
            back_url = '/admin/events'
        elif path.startswith('/admin/') and path != '/admin/login':
            back_url = '/admin'
        else:
            back_url = '/'
        return {'back_url': back_url}

    @app.after_request
    def fresh_state(response):
        if request.path == '/worker-state' or request.path.startswith(('/admin', '/event/')):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        return response
