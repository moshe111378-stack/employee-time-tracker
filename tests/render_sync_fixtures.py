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
