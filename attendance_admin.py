"""Attendance edits shared by the existing site variants.

Both historical audit schemas are supported in place; attendance and audit
records are never rewritten during initialization.
"""
import hmac
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import session


def audit_columns(connection):
    columns = {row[1] for row in connection.execute('PRAGMA table_info(att_edits)')}
    if {'attendance_id', 'admin_id', 'admin_name'} <= columns:
        return ('attendance_id', 'admin_id', 'admin_name')
    if {'att_id', 'edited_by_admin_id', 'editor_name'} <= columns:
        return ('att_id', 'edited_by_admin_id', 'editor_name')
    raise RuntimeError('Unsupported attendance audit schema; no records were changed')


def ensure_audit_schema(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS att_edits(
        id INTEGER PRIMARY KEY AUTOINCREMENT, attendance_id INTEGER NOT NULL,
        admin_id INTEGER, admin_name TEXT NOT NULL, old_cin TEXT, old_cout TEXT,
        new_cin TEXT NOT NULL, new_cout TEXT, edited_at TEXT NOT NULL)''')
    attendance, admin, name = audit_columns(connection)
    # Identifiers come only from the fixed schema mappings above.
    connection.execute(f'''CREATE VIEW IF NOT EXISTS attendance_edit_history AS
        SELECT id, {attendance} attendance_id, {attendance} att_id,
        {admin} admin_id, {admin} edited_by_admin_id,
        {name} admin_name, {name} editor_name,
        old_cin, old_cout, new_cin, new_cout, edited_at FROM att_edits''')
    connection.execute(f'''CREATE INDEX IF NOT EXISTS idx_attendance_edit_history
        ON att_edits({attendance},id)''')


def attendance_edit_token():
    if not session.get('attendance_edit_token'):
        session['attendance_edit_token'] = secrets.token_urlsafe(32)
    return session['attendance_edit_token']


def valid_edit_token(value):
    expected = session.get('attendance_edit_token', '')
    return bool(expected and value and hmac.compare_digest(expected.encode(), value.encode()))


def parse_edit_time(value, previous=None):
    if 'T' not in value:
        raise ValueError('יש להזין תאריך ושעה תקינים')
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('יש להזין תאריך ושעה תקינים') from None
    if result.tzinfo is not None:
        raise ValueError('יש להזין שעה מקומית ללא אזור זמן')
    local = result.replace(tzinfo=ZoneInfo('Asia/Jerusalem'))
    if local.astimezone(timezone.utc).astimezone(local.tzinfo).replace(tzinfo=None) != result:
        raise ValueError('השעה אינה קיימת עקב מעבר שעון')
    # The existing minute-resolution forms must not discard original seconds
    # when a manager changes only the other field or saves without a change.
    if previous and len(value) == 16:
        old = datetime.fromisoformat(previous)
        if old.replace(second=0, microsecond=0) == result:
            return previous
    return result.isoformat(timespec='seconds')


def save_attendance_edit(connection, event_id, attendance_id, admin_id, cin, cout):
    """Atomically update exactly one attendance row and append its audit entry."""
    try:
        connection.execute('BEGIN IMMEDIATE')
        admin = connection.execute('SELECT id,name FROM admins WHERE id=?', (admin_id,)).fetchone()
        if not admin:
            raise PermissionError('מנהל לא מורשה')
        row = connection.execute('SELECT * FROM att WHERE id=? AND event_id=?',
                                 (attendance_id, event_id)).fetchone()
        if not row:
            raise LookupError('דיווח לא נמצא')
        new_cin = parse_edit_time(cin.strip(), row['cin'])
        new_cout = parse_edit_time(cout.strip(), row['cout']) if cout.strip() else None
        if new_cout and datetime.fromisoformat(new_cout) <= datetime.fromisoformat(new_cin):
            raise ValueError('שעת היציאה חייבת להיות אחרי שעת הכניסה')
        if new_cout is None and connection.execute(
                'SELECT id FROM att WHERE worker_id=? AND cout IS NULL AND id<>? LIMIT 1',
                (row['worker_id'], attendance_id)).fetchone():
            raise ValueError('לעובד כבר יש דיווח פתוח אחר')
        if (new_cin, new_cout) == (row['cin'], row['cout']):
            connection.rollback()
            return False
        attendance, admin_col, name = audit_columns(connection)
        connection.execute(f'''INSERT INTO att_edits
            ({attendance},{admin_col},{name},old_cin,old_cout,new_cin,new_cout,edited_at)
            VALUES(?,?,?,?,?,?,?,?)''',
            (attendance_id, admin['id'], admin['name'], row['cin'], row['cout'],
             new_cin, new_cout, datetime.now(timezone.utc).isoformat(timespec='seconds')))
        connection.execute('UPDATE att SET cin=?,cout=? WHERE id=? AND event_id=?',
                           (new_cin, new_cout, attendance_id, event_id))
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def attendance_pay(row):
    if not row['cout'] or row['hourly_rate'] is None:
        return ''
    minutes = max(0, int((datetime.fromisoformat(row['cout']) -
                         datetime.fromisoformat(row['cin'])).total_seconds() / 60))
    return f"{minutes / 60 * float(row['hourly_rate']):.2f}"
