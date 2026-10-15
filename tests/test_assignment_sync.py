import importlib.util
import io
import re
import sqlite3
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv('DATA_DIR', str(tmp_path))
    monkeypatch.setenv('SECRET_KEY', 'isolated-test-key')
    monkeypatch.setenv('WORKER_DEVICE_AUTH_RESET_V1', '1')
    spec = importlib.util.spec_from_file_location('app', ROOT / 'app.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    c = module.con()
    c.executemany('insert into workers(id,name,phone,hourly_rate,device_code_hash) values(?,?,?,?,?)',
                  [(i, 'Test worker '+str(i), 'private-phone', 40, 'preserve-code') for i in range(1, 53)])
    c.executemany('insert into events(id,name,date,active) values(?,?,?,?)',
                  [(1,'Project A','2026-10-15',1),(2,'Project B','2026-10-15',1),(3,'Inactive','2026-10-15',0)])
    c.executemany('insert into ew values(?,?)', [(1,1),(1,2),(2,1),(3,1)])
    c.execute("insert into att(id,event_id,worker_id,cin,cout,pinphoto,inlat,inlon) values(1,1,1,'2026-10-15T08:00:32','2026-10-15T09:00:42','proof.jpg','1','2')")
    c.execute("insert into att_edits(attendance_id,admin_id,admin_name,new_cin,edited_at) values(1,1,'Admin','2026-10-15T08:00:32','2026-10-15T10:00:00')")
    c.commit(); c.close()
    client = module.app.test_client()
    with client.session_transaction() as s: s.update(aid=1, aname='Admin')
    return module, client, tmp_path


def form(client, event=1):
    html = client.get('/admin/event/'+str(event)).get_data(as_text=True)
    return {key: re.search(r'name="'+key+r'" value="([^"]*)"', html).group(1)
            for key in ['assignment_csrf','assignment_revision','assignments_present']}


def rows(module, table):
    c=module.con()
    try: return [tuple(r) for r in c.execute('select * from '+table+' order by 1')]
    finally: c.close()


def test_assignments_save_and_are_visible_to_an_already_open_client(site):
    module, admin, _ = site
    employee = module.app.test_client()
    assert employee.get('/worker-state?worker_id=4').json['events'] == []
    payload=form(admin); payload['worker_ids']=['1','2','3','4']
    before = {t:rows(module,t) for t in ['workers','att','att_edits','events']}
    assert admin.post('/admin/event/1',data=payload).status_code == 302
    assert employee.get('/worker-state?worker_id=4').json['events'] == [{'id':1,'name':'Project A'}]
    assert before == {t:rows(module,t) for t in before}
    assert (2,1) in rows(module,'ew')


def test_current_assignments_checked(site):
    html=site[1].get('/admin/event/1').get_data(as_text=True)
    assert 'עריכת שיוכים לאירוע' in html
    assert re.search(r'name="worker_ids" value="1" checked',html)
    assert not re.search(r'name="worker_ids" value="4" checked',html)


@pytest.mark.parametrize('path,target', [('/admin','/'),('/admin/events','/admin'),('/admin/workers','/admin'),('/admin/admins','/admin'),('/admin/reports','/admin'),('/admin/event/1','/admin/events'),('/event/1','/')])
def test_back_arrows(site,path,target):
    response=site[1].get(path)
    assert response.status_code == 200
    assert f'href="{target}" aria-label="חזרה אחורה"' in response.get_data(as_text=True)
    assert response.get_data(as_text=True).count('class="screen-back"') == 1


def test_login_and_worker_back_arrows(site):
    client=site[0].app.test_client()
    assert 'aria-label="חזרה אחורה"' in client.get('/admin/login').get_data(as_text=True)
    assert 'onclick="backToSplash()" aria-label="חזרה למסך הראשי"' in client.get('/').get_data(as_text=True)


@pytest.mark.parametrize('change', ['unknown','too_many','missing_marker','bad_token','malformed'])
def test_invalid_submission_keeps_all_assignments(site,change):
    module,client,_=site; payload=form(client); payload['worker_ids']=['1']
    if change=='unknown': payload['worker_ids']=['9999']
    elif change=='too_many': payload['worker_ids']=[str(i) for i in range(1,52)]
    elif change=='missing_marker': del payload['assignments_present']
    elif change=='bad_token': payload['assignment_csrf']='bad'
    elif change=='malformed': payload['worker_ids']=['1;delete from workers']
    before=rows(module,'ew')
    assert client.post('/admin/event/1',data=payload).status_code in (400,403)
    assert rows(module,'ew')==before


def test_stale_edit_cannot_overwrite_new_assignment(site):
    module,client,_=site; stale=form(client); fresh=dict(stale)
    fresh['worker_ids']=['1','3']
    assert client.post('/admin/event/1',data=fresh).status_code==302
    stale['worker_ids']=['2']
    assert client.post('/admin/event/1',data=stale).status_code==409
    assert (1,3) in rows(module,'ew') and (1,2) not in rows(module,'ew')


def test_authentication_required(site):
    module,admin,_=site; payload=form(admin); payload['worker_ids']=['4']
    anonymous=module.app.test_client()
    assert anonymous.post('/admin/event/1',data=payload).status_code==302
    with anonymous.session_transaction() as s: s.update(aid=999, assignment_csrf=payload['assignment_csrf'])
    assert anonymous.post('/admin/event/1',data=payload).status_code==403
    assert (1,4) not in rows(module,'ew')


def test_remove_preserves_hours_audit_and_open_shift_exit(site):
    module,client,_=site; c=module.con()
    c.execute("insert into att(id,event_id,worker_id,cin) values(2,1,2,'2026-10-15T08:00:00')");c.commit();c.close()
    payload=form(client); payload['worker_ids']=['1']; before=rows(module,'att')
    client.post('/admin/event/1',data=payload)
    state=client.get('/worker-state?worker_id=2').json
    assert state['events']==[] and state['open_shift']['event_id']==1
    assert rows(module,'att')==before
    worker=module.app.test_client()
    with worker.session_transaction() as s:s['worker_id']=2
    response=worker.post('/event/1',data={'wid':'2','act':'out'},headers={'X-Requested-With':'fetch'})
    assert response.status_code==200 and response.json['ok']
    assert len(rows(module,'att_edits'))==1


def test_no_new_clock_in_after_assignment_removed(site):
    module,admin,_=site; payload=form(admin); payload['worker_ids']=['1']; admin.post('/admin/event/1',data=payload)
    worker=module.app.test_client()
    with worker.session_transaction() as s:s['worker_id']=2
    before=rows(module,'att')
    assert worker.post('/event/1',data={'wid':'2','act':'in'},headers={'X-Requested-With':'fetch'}).status_code==409
    assert rows(module,'att')==before


def test_state_scope_cache_and_missing_worker(site):
    client=site[1]; r=client.get('/worker-state?worker_id=1')
    assert 'no-store' in r.headers['Cache-Control']
    assert [e['id'] for e in r.json['events']]==[1,2]
    assert all(set(w)=={'id','name'} for w in r.json['workers'])
    assert 'private-phone' not in r.get_data(as_text=True) and 'preserve-code' not in r.get_data(as_text=True)
    assert client.get('/worker-state?worker_id=999').json['worker_id'] is None
    assert client.get('/admin/event/999').status_code==404


def test_restart_preserves_assignment_and_enrollment(site):
    module,_,_=site; c=module.con();c.execute('update events set active=0 where id<>1');c.commit();c.close()
    before={t:rows(module,t) for t in ['ew','workers','att','att_edits']}
    spec=importlib.util.spec_from_file_location('app',ROOT/'app.py');reloaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(reloaded)
    assert before=={t:rows(reloaded,t) for t in before}


def test_can_clear_or_assign_fifty_without_deleting_history(site):
    module,client,_=site; payload=form(client);client.post('/admin/event/1',data=payload)
    assert all(e!=1 for e,w in rows(module,'ew'))
    payload=form(client);payload['worker_ids']=[str(i) for i in range(1,51)]
    assert client.post('/admin/event/1',data=payload).status_code==302
    assert len([r for r in rows(module,'ew') if r[0]==1])==50
    assert len(rows(module,'att'))==1 and len(rows(module,'att_edits'))==1
