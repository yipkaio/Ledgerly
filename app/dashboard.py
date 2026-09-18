"""Read-only workspace totals; human decisions and currencies stay separate."""

from collections import defaultdict
from datetime import datetime, timezone


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


def dashboard_summary(store) -> dict:
    counts = {state: 0 for state in ('AUTO_FILED', 'APPROVED', 'REJECTED', 'REVIEW_QUEUE', 'PROCESSING', 'FAILED')}
    currencies = defaultdict(lambda: {'total_cents': 0, 'receipt_count': 0, 'categories': [], 'months': []})
    accepted = " WHERE state IN ('AUTO_FILED','APPROVED') AND amount IS NOT NULL AND currency IS NOT NULL"
    cents = 'SUM(CAST(ROUND(amount * 100) AS INTEGER))'
    with store.connect() as db:
        db.execute('BEGIN')
        for row in db.execute(EFFECTIVE + 'SELECT state, count(*) AS count FROM effective GROUP BY state'):
            counts[row['state']] = row['count']
        incomplete = db.execute(EFFECTIVE + "SELECT count(*) FROM effective WHERE state IN ('AUTO_FILED','APPROVED') AND (amount IS NULL OR currency IS NULL)").fetchone()[0]
        for row in db.execute(EFFECTIVE + 'SELECT currency, count(*) AS count, ' + cents + ' AS cents FROM effective' + accepted + ' GROUP BY currency ORDER BY currency'):
            currencies[row['currency']].update(total_cents=row['cents'], receipt_count=row['count'])
        for row in db.execute(EFFECTIVE + "SELECT currency, COALESCE(category, 'Uncategorized') AS category, " + cents + ' AS cents FROM effective' + accepted + ' GROUP BY currency, category ORDER BY currency, cents DESC, category'):
            currencies[row['currency']]['categories'].append({'category': row['category'], 'total_cents': row['cents']})
        for row in db.execute(EFFECTIVE + 'SELECT currency, substr(date,1,7) AS month, ' + cents + ' AS cents FROM effective' + accepted + " AND date IS NOT NULL GROUP BY currency, month ORDER BY currency, month DESC"):
            months = currencies[row['currency']]['months']
            if len(months) < 12:
                months.append({'month': row['month'], 'total_cents': row['cents']})
    for value in currencies.values():
        value['months'].reverse()
    return {'counts': counts, 'total_receipts': sum(counts.values()), 'accepted_missing_value': incomplete,
            'currencies': [{'currency': code, **value} for code, value in currencies.items()],
            'generated_at': datetime.now(timezone.utc).isoformat()}
