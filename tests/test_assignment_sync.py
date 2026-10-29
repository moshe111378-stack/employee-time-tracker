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


@pytest.mark.parametrize('payload', [
    {'cin_date':'22/10/2026','cin_time':'19:02','cout_date':'23/10/2026','cout_time':'04:20'},
    {'cin_date':'22102026','cin_time':'1902','cout_date':'23102026','cout_time':'420'},
    {'cin':'2026-10-22T19:02','cout':'2026-10-23T04:20'},
])
def test_keyboard_hours_save_overnight_shift_and_audit(site,payload):
    module,client,_=site
    response=client.post('/admin/event/1/report/1/edit',data=payload,follow_redirects=True)
    assert response.status_code==200
    c=module.con()
    record=dict(c.execute('select * from att where id=1').fetchone())
    audit=dict(c.execute('select * from att_edits order by id desc limit 1').fetchone())
    c.close()
    assert record['cin']=='2026-10-22T19:02:00' and record['cout']=='2026-10-23T04:20:00'
    assert record['pinphoto']=='proof.jpg' and record['inlat']=='1'
    assert audit['old_cin']=='2026-10-15T08:00:32' and audit['new_cout']==record['cout']
    html=response.get_data(as_text=True)
    assert '9:18' in html and '372.00' in html


@pytest.mark.parametrize('changes', [
    {'cin_date':'31/02/2026'}, {'cin_time':'24:00'}, {'cin_time':'19:60'},
    {'cin_date':''}, {'cin_time':''}, {'cout_date':''}, {'cout_time':''},
    {'cout_date':'22/10/2026','cout_time':'18:00'},
    {'cin_date':'27/03/2026','cin_time':'02:30'},
])
def test_invalid_keyboard_times_never_change_records_or_audit(site,changes):
    module,client,_=site
    payload={'cin_date':'22/10/2026','cin_time':'19:02','cout_date':'23/10/2026','cout_time':'04:20'}
    payload.update(changes)
    before={table:rows(module,table) for table in ('att','att_edits')}
    client.post('/admin/event/1/report/1/edit',data=payload)
    assert before=={table:rows(module,table) for table in before}


def test_keyboard_edit_can_leave_shift_open_and_requires_admin(site):
    module,client,_=site
    payload={'cin_date':'22/10/2026','cin_time':'19:02','cout_date':'','cout_time':''}
    anonymous=module.app.test_client()
    before=rows(module,'att')
    response=anonymous.post('/admin/event/1/report/1/edit',data=payload)
    assert response.status_code==302 and response.location.endswith('/admin/login')
    assert before==rows(module,'att')
    client.post('/admin/event/1/report/1/edit',data=payload)
    c=module.con()
    assert c.execute('select cout from att where id=1').fetchone()['cout'] is None
    c.close()
    html=client.get('/admin/event/1').get_data(as_text=True)
    assert 'value="22/10/2026"' in html and 'value="19:02"' in html
    assert 'type="datetime-local"' not in html


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


@pytest.mark.parametrize('name,title', [('proof.jpg','תמונת כניסה'),('exit.jpg','תמונת יציאה')])
def test_attendance_photo_navigation_and_original_bytes(site,name,title):
    module,client,data=site
    image=b'\xff\xd8unchanged-original-photo\xff\xd9'
    (data/'uploads'/name).write_bytes(image)
    c=module.con();c.execute("update att set poutphoto='exit.jpg' where id=1");c.commit();c.close()
    before={t:rows(module,t) for t in ['att','att_edits','workers','ew']}
    # Current links explicitly request a viewer; old links work on navigation too.
    for suffix,headers in [('?view=1',{}),('',{'Accept':'text/html,application/xhtml+xml,image/avif,image/webp,*/*;q=0.8'})]:
        page=client.get('/uploads/'+name+suffix,headers=headers)
        html=page.get_data(as_text=True)
        assert page.status_code==200 and page.mimetype=='text/html'
        assert title in html
        assert 'href="/admin/event/1#report-1" aria-label="חזרה אחורה"' in html
        assert f'src="/uploads/{name}?raw=1"' in html
        assert 'no-store' in page.headers['Cache-Control']
    # An image load must stay an image, even with an unusual HTML Accept header.
    for suffix,headers in [('?raw=1',{'Accept':'text/html'}),('',{'Accept':'text/html','Sec-Fetch-Dest':'image'}),('',{})]:
        raw=client.get('/uploads/'+name+suffix,headers=headers)
        assert raw.mimetype=='image/jpeg' and raw.data==image
    report=client.get('/admin/event/1').get_data(as_text=True)
    assert f'href="/uploads/{name}?view=1"' in report
    assert f'href="/uploads/{name}?view=1" target="_blank"' not in report
    assert 'id="report-1"' in report
    assert before=={t:rows(module,t) for t in before}


def test_photo_viewer_keeps_admin_authentication_and_safe_paths(site):
    module,client,data=site
    (data/'uploads'/'proof.jpg').write_bytes(b'private-test-photo')
    anonymous=module.app.test_client()
    for suffix in ['?view=1','?raw=1','']:
        response=anonymous.get('/uploads/proof.jpg'+suffix)
        assert response.status_code==302 and response.location=='/admin/login'
    with anonymous.session_transaction() as s:s['aid']=999
    assert anonymous.get('/uploads/proof.jpg?view=1').status_code==403
    assert anonymous.get('/uploads/proof.jpg?raw=1').status_code==403
    assert client.get('/uploads/missing.jpg?view=1').status_code==404
    assert client.get('/uploads/..%2Fhours.db?view=1').status_code==404
