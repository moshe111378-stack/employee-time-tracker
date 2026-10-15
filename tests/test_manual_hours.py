import csv
import io
import re
import sqlite3
from pathlib import Path
import pytest
from test_assignment_sync import site, rows


def hidden(html,name):
    return re.search(r'name="'+name+r'" value="([^"]*)"',html).group(1)


def hours_form(client,event=1,start='2026-10-11',end='2026-10-15'):
    response=client.get(f'/admin/event/{event}/hours?start_date={start}&end_date={end}')
    assert response.status_code==200
    html=response.get_data(as_text=True)
    form={key:hidden(html,key) for key in ['csrf','form_token','revision','start_date','end_date']}
    form.update(worker_ids=['1','2'],hours_1='7',minutes_1='30',rate_1='40',hours_2='5',minutes_2='',rate_2='40',only_missing='1',note='השלמת השבוע')
    return form


def test_bulk_backdated_hours_without_punches_are_counted_everywhere(site):
    module,client,_=site
    before={table:rows(module,table) for table in ['att','att_edits','workers','ew','events']}
    response=client.post('/admin/event/1/hours',data=hours_form(client))
    assert response.status_code==302 and response.location.endswith('#manualHours')
    assert before=={table:rows(module,table) for table in before}
    c=module.con();manual=c.execute('select * from manual_hours order by worker_id').fetchall()
    assert [r['minutes'] for r in manual]==[450,300]
    assert all(r['start_date']=='2026-10-11' and r['end_date']=='2026-10-15' for r in manual)
    assert all(r['admin_name']=='מנהל ראשי' and r['admin_id']==1 for r in manual)
    assert client.get('/worker-state?worker_id=2').json['open_shift'] is None
    from period_reports import report_groups
    group=report_groups(c)[0];c.close()
    assert group['minutes']==810 and group['pay']==540 and group['worker_count']==2
    event=client.get('/admin/event/1').get_data(as_text=True)
    assert '<b>13:30</b>' in event and '<b>₪540.00</b>' in event
    assert 'הוזן ידנית על ידי מנהל ראשי' in event
    report=client.get('/admin/reports').get_data(as_text=True)
    assert 'data-minutes="300"' in report and 'שעות שהוזנו ידנית' in report
    exported=list(csv.reader(io.StringIO(client.get('/admin/event/1/export.csv').get_data(as_text=True).lstrip('\ufeff')),delimiter='\t'))
    assert len(exported)==4
    assert exported[1][1:4]==['2026-10-15T08:00:32','2026-10-15T09:00:42','1:00']
    assert exported[2][1:4]==['','','7:30']
    assert exported[2][7:12]==['שעות ידניות','2026-10-11','2026-10-15','40.00','300.00']


def test_one_previous_day_and_blank_rows(site):
    module,client,_=site;payload=hours_form(client,start='2026-10-12',end='2026-10-12')
    payload.update(hours_1='',minutes_1='',hours_2='8',minutes_2='15')
    assert client.post('/admin/event/1/hours',data=payload).status_code==302
    c=module.con();saved=c.execute('select worker_id,minutes,start_date,end_date from manual_hours').fetchall();c.close()
    assert [tuple(r) for r in saved]==[(2,495,'2026-10-12','2026-10-12')]


def test_repeat_submit_and_separate_stale_tabs_cannot_double_hours(site):
    module,client,_=site;first=hours_form(client);stale=hours_form(client)
    assert client.post('/admin/event/1/hours',data=first).status_code==302
    before=rows(module,'manual_hours')
    assert client.post('/admin/event/1/hours',data=first).status_code==302
    assert rows(module,'manual_hours')==before
    assert client.post('/admin/event/1/hours',data=stale).status_code==409
    assert rows(module,'manual_hours')==before
    first['hours_1']='9'
    assert client.post('/admin/event/1/hours',data=first).status_code==409
    assert rows(module,'manual_hours')==before


@pytest.mark.parametrize('change',[
    {'minutes_1':'60'},{'hours_1':'-1'},{'hours_1':'1.5'},{'hours_1':'9999'},
    {'rate_1':'NaN'},{'rate_1':'-40'},{'rate_1':'Infinity'},
    {'start_date':'2026-10-16','end_date':'2026-10-15'}, {'end_date':'2999-01-01'},
    {'start_date':'invalid'},{'worker_ids':['1','999']},{'only_missing':''}
])
def test_invalid_batch_writes_nothing_and_retains_inputs(site,change):
    module,client,_=site;payload=hours_form(client);payload.update(change)
    response=client.post('/admin/event/1/hours',data=payload)
    assert response.status_code in (400,409)
    assert not rows(module,'manual_hours') and not rows(module,'manual_hour_batches')
    assert 'role="alert"' in response.get_data(as_text=True)


def test_worker_anonymous_deleted_admin_and_wrong_form_cannot_add_hours(site):
    module,client,_=site;payload=hours_form(client)
    outsider=module.app.test_client()
    assert outsider.get('/admin/event/1/hours').status_code==302
    assert outsider.post('/admin/event/1/hours',data=payload).status_code==302
    with outsider.session_transaction() as s:s['worker_id']=1
    assert outsider.post('/admin/event/1/hours',data=payload).status_code==302
    with outsider.session_transaction() as s:s.update(aid=999,manual_hours_csrf=payload['csrf'])
    assert outsider.post('/admin/event/1/hours',data=payload).status_code==403
    wrong=dict(payload,csrf='wrong')
    assert client.post('/admin/event/1/hours',data=wrong).status_code==403
    assert client.post('/admin/event/2/hours',data=payload).status_code==403
    assert not rows(module,'manual_hours')


def test_concurrent_punch_or_assignment_change_requires_review(site):
    module,client,_=site;payload=hours_form(client)
    c=module.con();c.execute("insert into att(event_id,worker_id,cin,cout) values(1,2,'2026-10-14T10:00:00','2026-10-14T12:00:00')");c.commit();c.close()
    response=client.post('/admin/event/1/hours',data=payload)
    assert response.status_code==409 and not rows(module,'manual_hours')
    assert 'נוכחות 2:00 שעות' in response.get_data(as_text=True)


def test_cancel_preserves_audit_but_removes_hours_and_pay_from_totals(site):
    module,client,_=site;payload=hours_form(client);client.post('/admin/event/1/hours',data=payload)
    assert client.post('/admin/event/1/hours/1/cancel',data={'csrf':'wrong'}).status_code==403
    assert client.post('/admin/event/2/hours/1/cancel',data={'csrf':payload['csrf']}).status_code==404
    assert client.post('/admin/event/1/hours/1/cancel',data={'csrf':payload['csrf']}).status_code==302
    c=module.con();r=c.execute('select * from manual_hours where id=1').fetchone()
    assert r['minutes']==450 and r['cancelled_at'] and r['cancelled_by_name']=='מנהל ראשי'
    from period_reports import report_groups
    assert report_groups(c)[0]['minutes']==360 and report_groups(c)[0]['pay']==240
    c.close()
    event=client.get('/admin/event/1').get_data(as_text=True)
    assert '<b>6:00</b>' in event and '<b>₪240.00</b>' in event
    assert 'בוטל על ידי מנהל ראשי' in event
    assert '7:30' not in client.get('/admin/event/1/export.csv').get_data(as_text=True)


def test_rate_snapshot_missing_rate_and_formula_safe_export(site):
    module,client,_=site;payload=hours_form(client);payload.update(rate_2='',note='=HYPERLINK("example")')
    client.post('/admin/event/1/hours',data=payload)
    c=module.con();c.execute('update workers set hourly_rate=100 where id=1');c.commit()
    from period_reports import report_groups
    group=report_groups(c)[0];c.close()
    assert group['pay']==400 and group['unpriced']==1
    event=client.get('/admin/event/1').get_data(as_text=True)
    assert 'שכר לא הוגדר לדיווח זה' in event
    assert 'שכר לשעה: ₪40.00 · לתשלום: ₪300.00' in event
    exported=client.get('/admin/event/1/export.csv').get_data(as_text=True)
    data=list(csv.reader(io.StringIO(exported.lstrip('\ufeff')),delimiter='\t'))
    assert data[2][12].startswith("'=HYPERLINK") and data[3][10:12]==['','']


def event_csrf(client):
    return hidden(client.get('/admin/events').get_data(as_text=True),'csrf')


def test_create_year_long_event_and_update_existing_preserving_data(site):
    module,client,_=site;csrf=event_csrf(client)
    assert client.post('/admin/add-event',data={'csrf':csrf,'name':'Year project','date':'2026-01-01','end_date':'2026-12-31','worker_ids':['1','2']}).status_code==302
    c=module.con();event=c.execute("select * from events where name='Year project'").fetchone();c.close()
    assert event['date']=='2026-01-01' and event['end_date']=='2026-12-31'
    assert (event['id'],2) in rows(module,'ew')
    before={t:rows(module,t) for t in ['att','workers','ew','att_edits']}
    assert client.post('/admin/event/1/edit',data={'csrf':csrf,'name':'Project A','date':'2026-01-01','end_date':'2027-01-01'}).status_code==302
    assert before=={t:rows(module,t) for t in before}
    html=client.get('/admin/event/1').get_data(as_text=True)
    assert '2027-01-01' in html and 'הוספת שעות ידנית' in html


def test_invalid_event_range_and_non_admin_do_not_change_events(site):
    module,client,_=site;csrf=event_csrf(client);before=rows(module,'events')
    for target in ['/admin/add-event','/admin/event/1/edit']:
        response=client.post(target,data={'csrf':csrf,'name':'bad','date':'2026-12-31','end_date':'2026-01-01'})
        assert response.status_code==302
        assert client.post(target,data={'csrf':'bad','name':'bad','date':'2026-01-01','end_date':'2027-01-01'}).status_code==403
        assert module.app.test_client().post(target,data={'csrf':csrf}).status_code==302
    assert rows(module,'events')==before


def test_upgrade_of_legacy_database_is_additive_and_restart_safe(tmp_path,monkeypatch):
    import importlib.util
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('SECRET_KEY','isolated-upgrade-test')
    c=sqlite3.connect(tmp_path/'hours.db')
    c.executescript("create table events(id integer primary key,name text,date text,active integer default 1);insert into events values(1,'Existing event','2026-01-01',1);")
    c.commit();c.close()
    root=Path(__file__).resolve().parents[1]
    for _ in range(2):
        spec=importlib.util.spec_from_file_location('upgrade_app',root/'app.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        c=module.con()
        assert tuple(c.execute('select id,name,date,active,end_date from events').fetchone())==(1,'Existing event','2026-01-01',1,None)
        assert c.execute('select count(*) from manual_hours').fetchone()[0]==0
        c.close()
