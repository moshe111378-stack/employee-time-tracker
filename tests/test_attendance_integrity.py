import csv
import io
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from test_attendance_edit import site


def worker_client(module):
    client = module.app.test_client()
    with client.session_transaction() as sess:
        sess['worker_id'] = 1
    return client


def clock(client, event=1, act='in', photo=False):
    data = {'wid':'1','act':act,'lat':'31.7','lon':'35.2','acc':'4'}
    if photo:
        data['photo'] = (io.BytesIO(b'isolated-test-photo'), 'test.jpg')
    return client.post(f'/event/{event}', data=data, headers={'X-Requested-With':'fetch'})


def test_existing_worker_clock_photo_location_flow(site):
    module, admin, _ = site
    worker = worker_client(module)
    assert clock(worker, photo=True).status_code == 200
    assert clock(worker, act='out', photo=True).status_code == 200
    with module.con() as c:
        row=c.execute('SELECT * FROM att WHERE worker_id=1 ORDER BY id DESC').fetchone()
        assert row['cin'] and row['cout'] and row['pinphoto'] and row['poutphoto']
        assert row['inlat']==row['outlat']=='31.7'
    for path in ['/','/admin','/admin/workers','/admin/events','/admin/event/1','/admin/reports','/admin/event/1/export.csv']:
        assert admin.get(path).status_code == 200


def test_deleted_edit_does_not_attach_to_new_attendance(site):
    module, admin, token = site
    response=admin.post('/admin/event/2/report/2/edit',data={'edit_token':token,'cin':'2026-10-10T08:00','cout':'2026-10-10T13:00'})
    assert response.status_code == 302
    assert admin.post('/admin/event/2/report/2/delete').status_code == 302
    assert clock(worker_client(module)).status_code == 200
    with module.con() as c:
        newest=c.execute('SELECT * FROM att ORDER BY id DESC LIMIT 1').fetchone()
        history=c.execute('SELECT * FROM attendance_edit_history WHERE attendance_id=?',(newest['id'],)).fetchall()
        assert not history, f"New attendance id={newest['id']} for worker {newest['worker_id']} inherited {len(history)} old edits from deleted worker-2 attendance"


def test_worker_cannot_open_second_event_while_first_is_open(site):
    module, _, _ = site
    with module.con() as c:
        c.execute('INSERT INTO ew VALUES(2,1)')
    worker=worker_client(module)
    assert clock(worker).status_code==200
    clock(worker,event=2)
    with module.con() as c:
        count=c.execute('SELECT count(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0]
    assert count==1, f'Found {count} open shifts for one worker across events'


def run_parallel(module, monkeypatch, requests):
    """Start separate Flask/SQLite connections together, before either locks."""
    barrier = threading.Barrier(len(requests))
    original = module.record_attendance
    def simultaneous(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)
    monkeypatch.setattr(module, 'record_attendance', simultaneous)
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(lambda request: request(), requests))


def test_simultaneous_worker_clockins_cannot_duplicate(site, monkeypatch):
    module, _, _ = site
    replies = run_parallel(module, monkeypatch,
        [lambda: clock(worker_client(module), photo=True) for _ in range(4)])
    assert sorted(r.status_code for r in replies) == [200,409,409,409]
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0] == 1
    from pathlib import Path
    assert len(list(Path(module.UP).glob('*.jpg'))) == 1


def test_simultaneous_clockins_in_different_events(site, monkeypatch):
    module, _, _ = site
    with module.con() as c:
        c.execute('INSERT INTO ew VALUES(2,1)')
    replies = run_parallel(module, monkeypatch,
        [lambda e=e: clock(worker_client(module), event=e) for e in (1,2)])
    assert sorted(r.status_code for r in replies) == [200,409]
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0] == 1


def test_simultaneous_checkouts_save_once(site, monkeypatch):
    module, _, _ = site
    assert clock(worker_client(module)).status_code == 200
    replies=run_parallel(module, monkeypatch,
        [lambda: clock(worker_client(module), act='out', photo=True) for _ in range(2)])
    assert sorted(r.status_code for r in replies) == [200,409]
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0] == 0
    from pathlib import Path
    assert len(list(Path(module.UP).glob('*.jpg'))) == 1


def test_other_workers_can_clockin_concurrently(site, monkeypatch):
    module, _, _ = site
    def submit(wid):
        client=module.app.test_client()
        with client.session_transaction() as sess:sess['worker_id']=wid
        return client.post('/event/1',data={'wid':str(wid),'act':'in'},headers={'X-Requested-With':'fetch'})
    with module.con() as c:c.execute('INSERT INTO ew VALUES(1,2)')
    replies=run_parallel(module, monkeypatch,[lambda wid=wid:submit(wid) for wid in (1,2)])
    assert [r.status_code for r in replies] == [200,200]
    with module.con() as c:
        rows=c.execute('SELECT id,worker_id FROM att WHERE cout IS NULL').fetchall()
        assert len(rows)==2 and len({r['id'] for r in rows})==2


def test_worker_clockin_and_manager_reopen_are_serialized(site, monkeypatch):
    module, admin, token=site
    barrier=threading.Barrier(2)
    original_clock, original_edit=module.record_attendance,module.save_attendance_edit
    def clock_together(*a,**kw):
        barrier.wait(timeout=5)
        return original_clock(*a,**kw)
    def edit_together(*a,**kw):
        barrier.wait(timeout=5)
        return original_edit(*a,**kw)
    monkeypatch.setattr(module,'record_attendance',clock_together)
    monkeypatch.setattr(module,'save_attendance_edit',edit_together)
    def edit():
        return admin.post('/admin/event/1/report/1/edit',data={'edit_token':token,'cin':'2026-10-10T08:00','cout':''})
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies=list(pool.map(lambda f:f(),[edit,lambda:clock(worker_client(module))]))
    assert replies[0].status_code==302 and replies[1].status_code in (200,409)
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0]==1


def test_id_watermark_survives_all_deletions_and_reinitialization(site):
    module, admin, _=site
    from attendance_admin import ensure_audit_schema
    assert clock(worker_client(module)).status_code==200
    with module.con() as c:
        largest=c.execute('SELECT MAX(id) FROM att').fetchone()[0]
    assert admin.post(f'/admin/event/1/report/{largest}/delete').status_code==302
    assert admin.post('/admin/event/1/report/1/delete').status_code==302
    assert admin.post('/admin/event/2/report/2/delete').status_code==302
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att').fetchone()[0]==0
        ensure_audit_schema(c)
    assert clock(worker_client(module)).status_code==200
    with module.con() as c:
        assert c.execute('SELECT id FROM att').fetchone()[0]>largest


def test_old_orphan_audit_ids_are_reserved(site):
    module, _, _=site
    from attendance_admin import audit_columns, ensure_audit_schema
    with module.con() as c:
        att,aid,name=audit_columns(c)
        c.execute(f'''INSERT INTO att_edits({att},{aid},{name},old_cin,new_cin,edited_at)
            VALUES(900,1,'Old manager','2026-10-01T08:00:00','2026-10-01T09:00:00','2026-10-01T10:00:00Z')''')
        ensure_audit_schema(c)
        before=[tuple(r) for r in c.execute('SELECT * FROM att_edits ORDER BY id')]
    assert clock(worker_client(module)).status_code==200
    with module.con() as c:
        assert c.execute('SELECT MAX(id) FROM att').fetchone()[0]>900
        assert before==[tuple(r) for r in c.execute('SELECT * FROM att_edits ORDER BY id')]


def test_existing_duplicates_survive_initialization_and_block_new_entry(site):
    module, _, _=site
    from attendance_admin import ensure_audit_schema
    with module.con() as c:
        c.execute("INSERT INTO att(id,event_id,worker_id,cin) VALUES(10,1,1,'2026-10-10T14:00:00'),(11,2,1,'2026-10-10T14:00:01')")
        before=[tuple(r) for r in c.execute('SELECT * FROM att ORDER BY id')]
        ensure_audit_schema(c)
    assert clock(worker_client(module)).status_code==409
    with module.con() as c:
        assert before==[tuple(r) for r in c.execute('SELECT * FROM att ORDER BY id')]


def test_failed_clockin_rolls_back_rate_and_attendance(site):
    module, _, _=site
    with module.con() as c:
        c.execute('UPDATE workers SET hourly_rate=NULL WHERE id=1')
        old_state=c.execute('SELECT last_id FROM attendance_id_state').fetchone()[0]
        c.execute("CREATE TRIGGER reject_clock BEFORE INSERT ON att BEGIN SELECT RAISE(ABORT,'test failure'); END")
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        worker_client(module).post('/event/1',data={'wid':'1','act':'in','hourly_rate':'50'},headers={'X-Requested-With':'fetch'})
    with module.con() as c:
        assert c.execute('SELECT hourly_rate FROM workers WHERE id=1').fetchone()[0] is None
        assert c.execute('SELECT COUNT(*) FROM att').fetchone()[0]==2
        assert c.execute('SELECT last_id FROM attendance_id_state').fetchone()[0]==old_state


def test_busy_database_fails_cleanly_without_writing(site,monkeypatch):
    module, _, _=site
    original=module.con
    def short_timeout():
        c=original();c.execute('PRAGMA busy_timeout=20');return c
    monkeypatch.setattr(module,'con',short_timeout)
    lock=original();lock.execute('BEGIN IMMEDIATE')
    try:
        response=clock(worker_client(module))
        assert response.status_code==503 and response.json['ok'] is False
    finally:
        lock.rollback();lock.close()
    assert clock(worker_client(module)).status_code==200


def test_non_fetch_conflict_redirects_without_duplicate(site):
    module, _, _=site
    worker=worker_client(module)
    assert clock(worker).status_code==200
    response=worker.post('/event/1',data={'wid':'1','act':'in'})
    assert response.status_code==302
    with module.con() as c:
        assert c.execute('SELECT COUNT(*) FROM att WHERE worker_id=1 AND cout IS NULL').fetchone()[0]==1


def test_invalid_clock_action_has_no_side_effects(site):
    module, _, _=site
    assert clock(worker_client(module),act='invalid').status_code==400
    with module.con() as c:assert c.execute('SELECT COUNT(*) FROM att').fetchone()[0]==2


def test_legacy_checkout_remains_within_selected_event(site):
    module, _, _=site
    from attendance_admin import record_attendance
    from datetime import datetime
    with module.con() as c:
        c.execute("INSERT INTO att(id,event_id,worker_id,cin) VALUES(10,1,1,'2026-10-10T14:00:00'),(11,2,1,'2026-10-10T14:00:01')")
    c=module.con()
    try:
        result=record_attendance(c,1,1,'out',lambda:datetime(2026,10,10,15,0),lambda:None,(None,None,None),checkout_event_only=True)
        assert result['total']=='1:00'
        assert c.execute('SELECT cout FROM att WHERE id=10').fetchone()[0]=='2026-10-10T15:00:00'
        assert c.execute('SELECT cout FROM att WHERE id=11').fetchone()[0] is None
    finally:c.close()


def test_upgrade_preserves_original_table_rows_and_definitions(site):
    module, _, _=site
    from attendance_admin import ensure_audit_schema
    with module.con() as c:
        # Reconstruct the pre-upgrade state in this temporary database only.
        c.execute('DROP TRIGGER attendance_id_after_insert')
        c.execute('DROP TRIGGER attendance_id_before_delete')
        c.execute('DROP TABLE attendance_id_state')
        c.execute("INSERT INTO att(id,event_id,worker_id,cin) VALUES(10,1,1,'2026-10-10T14:00:00'),(11,2,1,'2026-10-10T14:00:01')")
        tables=['admins','workers','events','ew','att','att_edits']
        before={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}
        definitions={t:c.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(t,)).fetchone()[0] for t in tables}
        ensure_audit_schema(c)
        assert before=={t:[tuple(r) for r in c.execute(f'SELECT * FROM {t} ORDER BY rowid')] for t in tables}
        assert definitions=={t:c.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(t,)).fetchone()[0] for t in tables}
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'


def test_anonymous_worker_permissions_are_unchanged(site):
    module, _, _=site
    # The branding branch already allows anonymous clock-in. Other branches
    # require the existing worker-device session; this repair must retain it.
    if not hasattr(module,'ISRAEL_TZ'):
        assert clock(module.app.test_client()).status_code==200
        return
    response=clock(module.app.test_client())
    assert response.status_code==403
    with module.con() as c:assert c.execute('SELECT COUNT(*) FROM att').fetchone()[0]==2


def test_valid_new_hourly_rate_is_committed_with_clockin(site):
    module, _, _=site
    with module.con() as c:c.execute('UPDATE workers SET hourly_rate=NULL WHERE id=1')
    response=worker_client(module).post('/event/1',data={'wid':'1','act':'in','hourly_rate':'45'},headers={'X-Requested-With':'fetch'})
    assert response.status_code==200 and response.json['hourly']==45
    with module.con() as c:assert c.execute('SELECT hourly_rate FROM workers WHERE id=1').fetchone()[0]==45
