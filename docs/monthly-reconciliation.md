# Monthly bank reconciliation

Ledgerly can import a monthly bank statement CSV and compare debit transactions with active, accepted receipts for the same month and currency. The original CSV is retained in the authenticated workspace alongside normalized transactions.

## CSV input

The import is bounded to UTF-8 CSV files no larger than 2 MB and 5,000 rows. Headers are matched case-insensitively.

Required fields:

- `Date` (also accepts Transaction Date, Posting Date, or Value Date)
- `Description` (also accepts Details, Narrative, Merchant, or Payee)
- `Debit` or `Amount`

Optional fields are `Reference` and `Type`. A positive value in a Debit column is treated as money out. When only Amount is supplied, money out must be negative or the Type value must be Debit, Withdrawal, Payment, Purchase, or DR. Credits and blank debit rows are skipped and counted.

The UI provides a safe template:

```csv
Date,Description,Debit,Reference
2026-09-03,Example supplier,125.40,TXN-001
```

## Matching and status

Matching is deterministic and read-only. It uses exact currency and cents, a receipt-to-posting date gap of no more than seven days, and vendor text as supporting evidence. A match is withheld when multiple candidates are too close. It never changes receipt extraction, review, lifecycle, or bank data.

- **Paid** means the accepted receipt has a likely bank debit match.
- **No bank match** is an exception, not a conclusion that an invoice is unpaid.
- **Trade payable** and **Payment issue** are human-recorded audit events with actor, note, timestamp, and version.
- **Missing receipt** means a bank debit has no likely accepted receipt.
- **Duplicate transaction** identifies repeated date, amount, and normalized description values within imported statements for that month and currency.
- Existing receipt duplicate candidates remain visible as **Duplicate receipt**.

These exceptions are review signals, not proof of fraud. A person must inspect the source receipt, statement, and business context before escalating suspected fraud.

The monthly Excel workbook includes Summary, Bank transactions, and Receipts sheets. Exception rows are highlighted and currencies are kept separate.

## Cost prompts

Cost-saving prompts use only accepted receipt totals for the selected month. They identify the largest category and vendor concentration, then suggest review actions. Ledgerly does not invent current market prices or claim a supplier is cheaper without verified quotes.

## Singapore controls

The workflow preserves original receipt evidence, source statement CSVs, review and amendment history, payment follow-up events, and monthly exports. This supports record keeping and accountability but does not certify legal or tax compliance.

- [IRAS record keeping requirements](https://www.iras.gov.sg/taxes/corporate-income-tax/basics-of-corporate-income-tax/record-keeping-requirements) state that companies must retain source documents, accounting records, and bank statements for at least five years from the relevant Year of Assessment.
- [PDPC data protection obligations](https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act/data-protection-obligations) remain the organisation's responsibility, including appropriate protection, access, and retention practices.
- [CPF Board guidance on payments attracting CPF](https://www.cpf.gov.sg/employer/employer-obligations/what-payments-attract-cpf-contributions) distinguishes qualifying official-purpose reimbursements from wages. Finance or HR must review the facts; receipt classification alone cannot decide CPF treatment.

Back up the SQLite database and retained receipt files as one evidence set. Restrict the shared API key to trusted staff and devices.
