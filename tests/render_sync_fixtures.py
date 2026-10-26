"""Render synthetic fixtures for DOM tests. Never uses a production database."""
import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
with tempfile.TemporaryDirectory() as data:
    os.environ['DATA_DIR'] = data
    os.environ['SECRET_KEY'] = 'isolated-dom-fixture'
    import app
    app.app.config['SESSION_COOKIE_SECURE'] = False
    c = app.con()
    c.executemany('insert into workers(id,name,hourly_rate) values(?,?,?)', [(1,'Worker One',40),(2,'Worker Two',None)])
    c.executemany('insert into events(id,name,active) values(?,?,1)',[(1,'Event One'),(2,'Event Two')])
    c.executemany('insert into ew values(?,?)',[(1,1),(2,1)])
    c.commit();c.close()
    client=app.app.test_client()
    with client.session_transaction() as session: session['aid']=1
    destination=Path(sys.argv[1]);destination.mkdir(parents=True,exist_ok=True)
    (destination/'home.html').write_bytes(client.get('/').data)
    (destination/'event.html').write_bytes(client.get('/admin/event/1').data)
    # An old event with recent manual hours must still appear in a current-period report.
    c=app.con()
    c.execute("update events set date='2025-01-01',end_date='2027-12-31' where id=1")
    c.execute("insert into att(event_id,worker_id,cin,cout) values(1,1,'2026-10-15T08:00:00','2026-10-15T09:00:00')")
    c.executemany('insert into manual_hours(batch_token,event_id,worker_id,worker_name,start_date,end_date,minutes,rate_agorot,note,admin_id,admin_name,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?)',[
        ('fixture-one',1,1,'Worker One','2026-10-11','2026-10-15',450,4000,'',1,'Admin','2026-10-15T12:00:00'),
        ('fixture-two',1,2,'Worker Two','2026-09-01','2026-09-02',120,None,'',1,'Admin','2026-10-15T12:00:00'),
        ('fixture-three',1,1,'Worker One','2026-09-30','2026-10-02',120,4000,'',1,'Admin','2026-10-15T12:00:00')])
    c.commit()
    (destination/'attendance-edit.html').write_bytes(client.get('/admin/event/1').data)
    from period_reports import report_groups
    with app.app.test_request_context('/admin/reports'):
        html=app.render_template('admin_reports.html',reports=report_groups(c),today='2026-10-15')
    c.close()
    (destination/'reports.html').write_text(html)
    (destination/'manual-form.html').write_bytes(client.get('/admin/event/1/hours?start_date=2026-10-11&end_date=2026-10-15').data)
