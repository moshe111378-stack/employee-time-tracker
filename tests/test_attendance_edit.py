"""Exercise the real edit endpoint against disposable databases only."""
import sqlite3
from html.parser import HTMLParser

import pytest
from test_assignment_sync import site, rows

URL = '/admin/event/1/report/1/edit'
VALID = dict(cin_date='26/10/2026', cin_time='08:00', cout_date='26/10/2026', cout_time='19:02')


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') in VALID:
            self.values[attrs['name']] = attrs.get('value', '')


def snapshot(module):
    return {t: rows(module, t) for t in ('att', 'att_edits', 'workers', 'events', 'ew', 'manual_hours')}


@pytest.mark.parametrize('missing,message', [('cout_date', 'חסר תאריך יציאה.'), ('cout_time', 'חסרה שעת יציאה.')])
@pytest.mark.parametrize('value', ['', '  ', None])
@pytest.mark.parametrize('ajax', [False, True])
def test_partial_exit_returns_field_error_without_any_write(site, missing, message, value, ajax):
    module, client, _ = site
    payload = dict(VALID)
    if value is None:
        del payload[missing]
    else:
        payload[missing] = value
    before = snapshot(module)
    response = client.post(URL, data=payload, headers={'X-Requested-With': 'fetch'} if ajax else {})
    assert response.status_code == 422 and 'Location' not in response.headers
    if ajax:
        assert response.json == dict(ok=False, error=message, errors={missing: message})
    else:
        html = response.get_data(as_text=True)
        assert message in html
        assert 'data-error-for="'+missing+'"' in html
        assert Inputs(html).values == {k: payload.get(k, '') for k in VALID}
        assert 'open>' in html and 'method="post"' in html
    assert snapshot(module) == before


@pytest.mark.parametrize('changes,expected', [
    ({}, '2026-10-26T19:02:00'),
    ({'cout_date': '', 'cout_time': ''}, None),
    ({'cout_date': '  ', 'cout_time': '  '}, None),
    ({'cin_time': '22:00', 'cout_date': '27/10/2026', 'cout_time': '04:20'}, '2026-10-27T04:20:00'),
    ({'cin_date': '26102026', 'cin_time': '800', 'cout_date': '26102026', 'cout_time': '1902'}, '2026-10-26T19:02:00'),
])
def test_valid_fetch_save_keeps_existing_audit_and_calculations(site, changes, expected):
    module, client, _ = site
    payload = {**VALID, **changes}
    before = snapshot(module)
    response = client.post(URL, data=payload, headers={'X-Requested-With': 'fetch'})
    assert response.status_code == 200
    assert response.json == dict(ok=True, redirect='/admin/event/1#report-1')
    after = snapshot(module)
    for table in ('workers', 'events', 'ew', 'manual_hours'):
        assert after[table] == before[table]
    assert len(after['att']) == len(before['att']) and len(after['att_edits']) == len(before['att_edits']) + 1
    # Existing photo and location evidence is retained byte for byte.
    assert after['att'][0][5:] == before['att'][0][5:]
    assert after['att'][0][4] == expected
    assert after['att_edits'][-1][4:6] == before['att'][0][3:5]
    if not changes:
        html = client.get('/admin/event/1').get_data(as_text=True)
        assert '11:02' in html and '441.33' in html


@pytest.mark.parametrize('changes', [
    {'cout_date': '31/02/2026'}, {'cout_time': '24:00'},
    {'cin_date': '27/03/2026', 'cin_time': '02:30'},
    {'cin_time': '22:00', 'cout_time': '04:20'},
])
def test_invalid_dates_times_and_same_day_overnight_are_preserved_without_guessing(site, changes):
    module, client, _ = site
    payload = {**VALID, **changes}
    before = snapshot(module)
    response = client.post(URL, data=payload)
    assert response.status_code == 422
    assert Inputs(response.get_data(as_text=True)).values == payload
    assert snapshot(module) == before


def test_rendered_input_is_escaped_and_not_stored_in_session(site):
    module, client, _ = site
    payload = {**VALID, 'cout_date': '"><script>alert(1)</script>'}
    before = snapshot(module)
    response = client.post(URL, data=payload)
    html = response.get_data(as_text=True)
    assert '<script>alert(1)</script>' not in html
    assert Inputs(html).values == payload
    with client.session_transaction() as session:
        assert not any(value in str(dict(session)) for value in payload.values())
    assert snapshot(module) == before


@pytest.mark.parametrize('ajax', [False, True])
def test_database_error_rolls_back_attendance_and_audit_and_keeps_edit(site, ajax):
    module, client, _ = site
    c = module.con()
    # Failure after UPDATE: both writes must still roll back as one transaction.
    c.execute("CREATE TRIGGER reject_edit BEFORE INSERT ON att_edits BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    c.commit(); c.close()
    before = snapshot(module)
    response = client.post(URL, data=VALID, headers={'X-Requested-With': 'fetch'} if ajax else {})
    assert response.status_code == 503
    assert 'test failure' not in response.get_data(as_text=True)
    if ajax:
        assert response.json['ok'] is False and 'השמירה נכשלה' in response.json['error']
    else:
        assert Inputs(response.get_data(as_text=True)).values == VALID
    assert snapshot(module) == before
    # A deliberate retry succeeds once the transient cause is removed.
    c = module.con(); c.execute('DROP TRIGGER reject_edit'); c.commit(); c.close()
    assert client.post(URL, data=VALID).status_code == 302
    assert len(rows(module, 'att_edits')) == len(before['att_edits']) + 1


def test_connection_failure_can_render_retry_without_database(site, monkeypatch):
    module, client, _ = site
    before = snapshot(module)
    def unavailable():
        raise sqlite3.OperationalError('test connection unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(module, 'con', unavailable)
        response = client.post(URL, data=VALID)
        assert response.status_code == 503
        assert Inputs(response.get_data(as_text=True)).values == VALID
    assert snapshot(module) == before


def test_conflicting_open_shift_and_wrong_event_preserve_input(site):
    module, client, _ = site
    c = module.con()
    c.execute("INSERT INTO att(event_id,worker_id,cin) VALUES(2,1,'2026-10-26T20:00:00')")
    c.commit(); c.close()
    before = snapshot(module)
    payload = {**VALID, 'cout_date': '', 'cout_time': ''}
    response = client.post(URL, data=payload)
    assert response.status_code == 409
    assert Inputs(response.get_data(as_text=True)).values == payload
    response = client.post('/admin/event/2/report/1/edit', data=VALID)
    assert response.status_code == 404
    assert Inputs(response.get_data(as_text=True)).values == VALID
    assert snapshot(module) == before


def test_older_datetime_form_can_retry_after_validation_failure(site):
    module, client, _ = site
    before = snapshot(module)
    response = client.post(URL, data={'cin': '2026-10-26T22:00', 'cout': '2026-10-26T04:20'})
    assert response.status_code == 422
    assert Inputs(response.get_data(as_text=True)).values == dict(cin_date='26/10/2026', cin_time='22:00', cout_date='26/10/2026', cout_time='04:20')
    assert snapshot(module) == before
