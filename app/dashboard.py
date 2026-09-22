"""Read-only workspace totals; human decisions and currencies stay separate."""

from collections import defaultdict
from datetime import date, datetime, timezone

from app.fx import FXUnavailable, convert_cents, workspace_currency


EFFECTIVE = """WITH effective AS (
 SELECT COALESCE(json_extract(v.result_json, '$.decision'), c.decision, r.processing_status) AS state,
 COALESCE(json_extract(a.result_json, '$.final_data.total_amount'), json_extract(v.result_json, '$.final_data.total_amount'), json_extract(r.extraction_json, '$.total_amount')) AS amount,
 COALESCE(json_extract(a.result_json, '$.final_data.currency'), json_extract(v.result_json, '$.final_data.currency'), json_extract(r.extraction_json, '$.currency')) AS currency,
 COALESCE(json_extract(a.result_json, '$.category'), json_extract(v.result_json, '$.category'), json_extract(c.result_json, '$.category')) AS category,
 COALESCE(json_extract(a.result_json, '$.final_data.date'), json_extract(v.result_json, '$.final_data.date'), json_extract(r.extraction_json, '$.date')) AS date
 FROM receipts r LEFT JOIN classifications c USING(receipt_id) LEFT JOIN receipt_reviews v USING(receipt_id)
 LEFT JOIN receipt_amendments a ON a.receipt_id=r.receipt_id
 AND a.version=(SELECT max(a2.version) FROM receipt_amendments a2 WHERE a2.receipt_id=r.receipt_id)
 WHERE r.lifecycle_state='ACTIVE'
) """


def dashboard_summary(
    store,
    fx_snapshot: dict | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    dated_only: bool = False,
) -> dict:
    counts = {state: 0 for state in ('AUTO_FILED', 'APPROVED', 'REJECTED', 'REVIEW_QUEUE', 'PROCESSING', 'FAILED')}
    currencies = defaultdict(lambda: {'total_cents': 0, 'receipt_count': 0, 'categories': [], 'months': []})
    range_conditions = []
    range_values: list[str] = []
    if date_from is not None:
        range_conditions.append('date >= ?')
        range_values.append(date_from.isoformat())
    if date_to is not None:
        range_conditions.append('date <= ?')
        range_values.append(date_to.isoformat())
    if dated_only:
        range_conditions.append('date IS NOT NULL')
    range_sql = ''.join(f' AND {condition}' for condition in range_conditions)
    accepted_state = " WHERE state IN ('AUTO_FILED','APPROVED')" + range_sql
    accepted_values = accepted_state + ' AND amount IS NOT NULL AND currency IS NOT NULL'
    cents = 'SUM(CAST(ROUND(amount * 100) AS INTEGER))'
    with store.connect() as db:
        db.execute('BEGIN')
        for row in db.execute(EFFECTIVE + 'SELECT state, count(*) AS count FROM effective GROUP BY state'):
            counts[row['state']] = row['count']
        bounds = db.execute(
            EFFECTIVE
            + "SELECT min(date) AS first, max(date) AS last FROM effective "
            + "WHERE state IN ('AUTO_FILED','APPROVED') AND date IS NOT NULL"
        ).fetchone()
        accepted_count = db.execute(
            EFFECTIVE + 'SELECT count(*) FROM effective' + accepted_state,
            range_values,
        ).fetchone()[0]
        incomplete = db.execute(
            EFFECTIVE + 'SELECT count(*) FROM effective' + accepted_state
            + ' AND (amount IS NULL OR currency IS NULL)',
            range_values,
        ).fetchone()[0]
        for row in db.execute(EFFECTIVE + 'SELECT currency, count(*) AS count, ' + cents + ' AS cents FROM effective' + accepted_values + ' GROUP BY currency ORDER BY currency', range_values):
            currencies[row['currency']].update(total_cents=row['cents'], receipt_count=row['count'])
        for row in db.execute(EFFECTIVE + "SELECT currency, COALESCE(category, 'Uncategorized') AS category, " + cents + ' AS cents FROM effective' + accepted_values + ' GROUP BY currency, category ORDER BY currency, cents DESC, category', range_values):
            currencies[row['currency']]['categories'].append({'category': row['category'], 'total_cents': row['cents']})
        for row in db.execute(
            EFFECTIVE
            + 'SELECT currency, substr(date,1,7) AS month, count(*) AS count, '
            + cents
            + ' AS cents FROM effective'
            + accepted_values
            + " AND date IS NOT NULL GROUP BY currency, month ORDER BY currency, month DESC",
            range_values,
        ):
            months = currencies[row['currency']]['months']
            months.append({
                'month': row['month'],
                'total_cents': row['cents'],
                'receipt_count': row['count'],
            })
    for value in currencies.values():
        value['months'].reverse()
    default_currency = workspace_currency(store)
    reporting = None
    if default_currency:
        reporting = {'currency': default_currency, 'available': False,
                     'total_cents': None, 'receipt_count': 0, 'categories': [], 'months': [],
                     'as_of': None, 'source': None, 'stale': False, 'components': []}
        if fx_snapshot:
            category_totals = defaultdict(int)
            month_totals = defaultdict(int)
            month_counts = defaultdict(int)
            total = 0
            try:
                for code, value in currencies.items():
                    converted = convert_cents(value['total_cents'], code, default_currency,
                                              fx_snapshot['rates'])
                    total += converted
                    reporting['receipt_count'] += value['receipt_count']
                    reporting['components'].append({
                        'currency': code, 'original_cents': value['total_cents'],
                        'converted_cents': converted,
                    })
                    for item in value['categories']:
                        category_totals[item['category']] += convert_cents(
                            item['total_cents'], code, default_currency, fx_snapshot['rates'])
                    for item in value['months']:
                        month_counts[item['month']] += item['receipt_count']
                        month_totals[item['month']] += convert_cents(
                            item['total_cents'], code, default_currency, fx_snapshot['rates'])
                reporting.update(
                    available=True, total_cents=total, as_of=fx_snapshot['as_of'],
                    source=fx_snapshot['source'], stale=fx_snapshot.get('stale', False),
                    categories=[{'category': key, 'total_cents': value} for key, value in
                                sorted(category_totals.items(), key=lambda pair: (-pair[1], pair[0]))],
                    months=[{'month': key, 'total_cents': value,
                             'receipt_count': month_counts[key]} for key, value in
                            sorted(month_totals.items())],
                )
            except FXUnavailable:
                pass
    return {'counts': counts, 'total_receipts': sum(counts.values()),
            'accepted_count': accepted_count, 'accepted_missing_value': incomplete,
            'accepted_date_bounds': {'first': bounds['first'], 'last': bounds['last']},
            'date_range': {'from': date_from.isoformat() if date_from else None,
                           'to': date_to.isoformat() if date_to else None},
            'currencies': [{'currency': code, **value} for code, value in currencies.items()],
            'default_currency': default_currency, 'reporting': reporting,
            'generated_at': datetime.now(timezone.utc).isoformat()}
