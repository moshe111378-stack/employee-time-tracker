"""Combine ordinary attendance and explicit period totals without fake punches."""
import csv
import io
import math
from datetime import datetime
from manual_hours import hours_text, manual_rows, money_text


def safe_rate(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def attendance_minutes(row):
    if not row['cout']:
        return 0
    try:
        return max(0,int((datetime.fromisoformat(row['cout'])-datetime.fromisoformat(row['cin'])).total_seconds()/60))
    except (ValueError, TypeError):
        return 0


def report_groups(connection):
    records = []
    rows = connection.execute('''select a.*,w.name worker_name,w.hourly_rate,e.name event_name,e.date event_date,
       e.end_date event_end_date,
       (select x.admin_name from att_edits x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin,
       (select x.edited_at from att_edits x where x.attendance_id=a.id order by x.id desc limit 1) edited_at
       from att a join workers w on w.id=a.worker_id join events e on e.id=a.event_id
       where a.cout is not null order by e.date desc,a.id desc''')
    for row in rows:
        minutes = attendance_minutes(row); rate = safe_rate(row['hourly_rate'])
        records.append(dict(row,manual=False,minutes=minutes,rate=rate,pay=minutes/60*(rate or 0),
                            start_date=row['cin'][:10],end_date=row['cout'][:10]))
    for row in manual_rows(connection):
        records.append(dict(row,manual=True,rate=None if row['rate_agorot'] is None else row['rate_agorot']/100,
                            pay=(row['pay_agorot'] or 0)/100,edit_admin=None,edited_at=None))
    groups = {}
    for row in records:
        event = groups.setdefault(row['event_id'],{'id':row['event_id'],'name':row['event_name'],'date':row['event_date'],
            'end_date':row['event_end_date'],'minutes':0,'pay':0.0,'workers':set(),'rows':[],'unpriced':0})
        event['minutes'] += row['minutes']; event['pay'] += row['pay']
        event['workers'].add(row['worker_id']); event['rows'].append(row)
        event['unpriced'] += row['rate'] is None
    for event in groups.values():
        event['worker_count'] = len(event['workers'])
        event['hours'] = hours_text(event['minutes']); event['pay_text'] = f"{event['pay']:.2f}"
        event['rows'].sort(key=lambda row: (row['end_date'],row['id']),reverse=True)
    return sorted(groups.values(),key=lambda event: max(r['end_date'] for r in event['rows']),reverse=True)


def export_rows(connection, event_id, duration):
    output = io.StringIO(); output.write('\ufeff')
    writer = csv.writer(output,delimiter='\t')
    writer.writerow(['עובד','כניסה','יציאה','סהכ שעות','מיקום כניסה','מיקום יציאה','נערך על ידי מנהל',
                     'סוג דיווח','מתאריך','עד תאריך','שכר לשעה','לתשלום','הערה','הוזן על ידי','מועד הזנה'])
    def write(values):
        writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in values])
    rows = connection.execute('''select a.*,w.name,w.hourly_rate,
       (select x.admin_name from att_edits x where x.attendance_id=a.id order by x.id desc limit 1) edit_admin
       from att a join workers w on w.id=a.worker_id where a.event_id=? order by a.id''',(event_id,))
    for row in rows:
        rate = safe_rate(row['hourly_rate'])
        pay = f"{attendance_minutes(row)/60*rate:.2f}" if row['cout'] and rate is not None else ''
        write([row['name'],row['cin'],row['cout'] or '',duration(row['cin'],row['cout']),
               f"{row['inlat'] or ''},{row['inlon'] or ''}",f"{row['outlat'] or ''},{row['outlon'] or ''}",
               'נערך על ידי מנהל' if row['edit_admin'] else '', 'נוכחות','','',
               '' if rate is None else f'{rate:.2f}',pay,'','',''])
    for row in reversed(manual_rows(connection,event_id)):
        write([row['worker_name'],'','',hours_text(row['minutes']),'','','', 'שעות ידניות',
               row['start_date'],row['end_date'],money_text(row['rate_agorot']),money_text(row['pay_agorot']),
               row['note'],row['admin_name'],row['created_at']])
    return output.getvalue()
