import csv
import importlib.util
import io
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(params=['new', 'canonical', 'legacy'])
def site(request, tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SECRET_KEY', 'isolated-test-secret')
    monkeypatch.setenv('ADMIN_PASSWORD', 'isolated-test-password')
    monkeypatch.delenv('MASTER_TIME_TEST', raising=False)
    db = tmp_path/'hours.db'
    if request.param != 'new':
        fields = ('attendance_id INTEGER NOT NULL,admin_id INTEGER,admin_name TEXT NOT NULL'
                  if request.param == 'canonical' else
                  'att_id INTEGER NOT NULL,edited_by_admin_id INTEGER NOT NULL,editor_name TEXT NOT NULL')
        with sqlite3.connect(db) as c:
            c.execute(f'''CREATE TABLE att_edits(id INTEGER PRIMARY KEY,{fields},
                old_cin TEXT,old_cout TEXT,new_cin TEXT NOT NULL,new_cout TEXT,edited_at TEXT NOT NULL)''')
            c.execute('INSERT INTO att_edits VALUES(99,88,1,?,?,?,?,?,?)',
                      ('Original manager','2026-10-01T08:00:00',None,'2026-10-01T09:00:00',None,'2026-10-01T10:00:00Z'))
    name = 'attendance_site_'+uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, ROOT/'app.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    with module.con() as c:
        c.execute("INSERT INTO events(id,name,date) VALUES(1,'Test event','2026-10-10'),(2,'Other event','2026-10-10')")
        c.execute("INSERT INTO workers(id,name,phone,hourly_rate) VALUES(1,'Test worker','',60),(2,'Other worker','',80)")
        c.execute('INSERT INTO ew VALUES(1,1)')
        c.execute('''INSERT INTO att(id,event_id,worker_id,cin,cout,pinphoto,inlat,inlon)
            VALUES(1,1,1,'2026-10-10T08:00:00','2026-10-10T12:00:00','keep.jpg','31','35')''')
        c.execute("INSERT INTO att(id,event_id,worker_id,cin,cout) VALUES(2,2,2,'2026-10-10T08:00:00','2026-10-10T12:00:00')")
    client = module.app.test_client()
    with client.session_transaction() as session:
        session['aid'] = 1
        session['aname'] = 'Untrusted cached name'
    response = client.get('/admin/event/1')
    assert response.status_code == 200
    with client.session_transaction() as session:
        token = session['attendance_edit_token']
    yield module, client, token
    sys.modules.pop(name, None)


def post(site, **changes):
    _, client, token = site
    data = dict(cin='2026-10-10T08:00',cout='2026-10-10T13:30',edit_token=token)
    data.update(changes)
    return client.post('/admin/event/1/report/1/edit', data=data)


def test_edit_updates_one_row_audit_totals_and_export(site):
    module, client, _ = site
    assert post(site).status_code == 302
    with module.con() as c:
        row = c.execute('SELECT * FROM att WHERE id=1').fetchone()
        assert row['cout'] == '2026-10-10T13:30:00'
        assert (row['pinphoto'],row['inlat'],row['inlon']) == ('keep.jpg','31','35')
        assert c.execute('SELECT cout FROM att WHERE id=2').fetchone()[0] == '2026-10-10T12:00:00'
        audit = c.execute('SELECT * FROM attendance_edit_history WHERE attendance_id=1').fetchone()
        assert audit['old_cout'] == '2026-10-10T12:00:00'
        assert audit['new_cout'] == row['cout']
        assert audit['admin_name'] == 'מנהל ראשי'
    for path in ['/admin/event/1','/admin/reports']:
        html = client.get(path).get_data(as_text=True)
        assert 'נערך על ידי מנהל' in html and '330.00' in html
    response = client.get('/admin/event/1/export.csv')
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True).lstrip('\ufeff')),delimiter='\t'))
    assert rows[0]['שכר לשעה'] == '60.00'
    assert rows[0]['סהכ לתשלום'] == '330.00'
    assert rows[0]['סהכ שעות'] == '5:30'
    assert 'מנהל ראשי' in rows[0]['נערך על ידי מנהל']


@pytest.mark.parametrize('changes',[
    {'cout':'2026-10-10T07:00'}, {'cout':'2026-10-10T08:00'},
    {'cin':'not-a-date'}, {'cin':'2026-10-10'},
    {'cin':'2026-10-10T08:00+03:00'}, {'cin':'2026-03-27T02:30'},
])
def test_invalid_time_does_not_change_records(site, changes):
    module, _, _ = site
    assert post(site, **changes).status_code == 302
    with module.con() as c:
        assert c.execute('SELECT cout FROM att WHERE id=1').fetchone()[0] == '2026-10-10T12:00:00'
        assert c.execute('SELECT COUNT(*) FROM attendance_edit_history WHERE attendance_id=1').fetchone()[0] == 0


@pytest.mark.parametrize('worker_id', [None, 1])
def test_worker_and_anonymous_cannot_edit(site, worker_id):
    module, client, _ = site
    with client.session_transaction() as session:
        session.pop('aid')
        session['worker_id'] = worker_id
    assert post(site).status_code == 302
    with module.con() as c:
        assert c.execute('SELECT cout FROM att WHERE id=1').fetchone()[0] == '2026-10-10T12:00:00'


def test_removed_admin_cannot_edit(site):
    _, client, _ = site
    with client.session_transaction() as session:
        session['aid'] = 999
    assert post(site).status_code == 403


@pytest.mark.parametrize('token', ['', 'wrong', 'שגוי'])
def test_csrf_required(site, token):
    assert post(site, edit_token=token).status_code == 400


def test_event_boundary(site):
    _, client, token = site
    assert client.post('/admin/event/2/report/1/edit',data={'edit_token':token,'cin':'2026-10-10T08:00','cout':''}).status_code == 404


def test_duplicate_open_shift_rejected(site):
    module, _, _ = site
    with module.con() as c:
        c.execute("INSERT INTO att(id,event_id,worker_id,cin) VALUES(3,2,1,'2026-10-10T14:00:00')")
    assert post(site,cout='').status_code == 302
    with module.con() as c:
        assert c.execute('SELECT cout FROM att WHERE id=1').fetchone()[0] is not None


def test_unchanged_minutes_preserve_seconds_without_audit(site):
    module, _, _ = site
    with module.con() as c:
        c.execute("UPDATE att SET cin='2026-10-10T08:00:25',cout='2026-10-10T12:00:30' WHERE id=1")
    assert post(site,cout='2026-10-10T12:00').status_code == 302
    with module.con() as c:
        assert c.execute('SELECT cin,cout FROM att WHERE id=1').fetchone()[:] == ('2026-10-10T08:00:25','2026-10-10T12:00:30')
        assert c.execute('SELECT COUNT(*) FROM attendance_edit_history WHERE attendance_id=1').fetchone()[0] == 0


def test_open_shift_export_has_no_final_pay(site):
    _, client, _ = site
    assert post(site,cout='').status_code == 302
    rows = list(csv.DictReader(io.StringIO(client.get('/admin/event/1/export.csv').get_data(as_text=True).lstrip('\ufeff')),delimiter='\t'))
    assert rows[0]['סהכ לתשלום'] == ''


def test_audit_failure_rolls_back_attendance(site):
    module, _, _ = site
    with module.con() as c:
        c.execute("CREATE TRIGGER reject_edit BEFORE INSERT ON att_edits BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        post(site)
    with module.con() as c:
        assert c.execute('SELECT cout FROM att WHERE id=1').fetchone()[0] == '2026-10-10T12:00:00'


def test_initialization_preserves_audit_rows(site):
    module, _, _ = site
    from attendance_admin import ensure_audit_schema
    with module.con() as c:
        before = [tuple(r) for r in c.execute('SELECT * FROM att_edits ORDER BY id')]
        attendance = [tuple(r) for r in c.execute('SELECT * FROM att ORDER BY id')]
        ensure_audit_schema(c)
        assert before == [tuple(r) for r in c.execute('SELECT * FROM att_edits ORDER BY id')]
        assert attendance == [tuple(r) for r in c.execute('SELECT * FROM att ORDER BY id')]
