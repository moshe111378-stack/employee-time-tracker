"""Event date ranges; the historical date column remains the start date."""
import hmac
from datetime import date
from flask import abort, request, session


def validate_event_form(connection):
    if not connection.execute('select id from admins where id=?',(session.get('aid'),)).fetchone():
        abort(403)
    token=session.get('event_dates_csrf','')
    if not token or not hmac.compare_digest(token,request.form.get('csrf','')):
        abort(403,description='יש לרענן את מסך האירועים לפני השמירה.')


def event_period(values):
    try:
        start=date.fromisoformat(values.get('date',''))
        end=date.fromisoformat(values.get('end_date',''))
    except (ValueError,TypeError):
        raise ValueError('יש לבחור תאריך התחלה ותאריך סיום לאירוע.')
    if end<start:
        raise ValueError('תאריך הסיום חייב להיות באותו יום או אחרי תאריך ההתחלה.')
    return start.isoformat(),end.isoformat()
