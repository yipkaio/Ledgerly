# Monthly bank reconciliation

Ledgerly can import a monthly bank statement PDF or normalized CSV and compare debit transactions with active, accepted receipts for the same month and currency. The original confirmed source is retained in the authenticated workspace alongside normalized transactions.

Month detail reads payment follow-up events for receipts in the selected period
and shows both the latest state and the full event history. The
[maintenance review](maintenance-review.md) explains the remaining overview
query cost for workspaces with many recorded periods.

## Find months that need review

Monthly Close opens on an overview of periods with an accepted receipt or an imported statement, including receipt-only months that have no statement. Select a year or show all years, and filter to periods needing attention. The overview lists missing statements, unmatched bank debits, receipts without a bank match, possible duplicates and the recorded review state. It does not assume that a month with no receipts or statements had bank activity; such months remain unlisted. Period amounts and reconciliation stay in their original currency.

Open a month to inspect the bank debits, accepted receipts, retained statement and original receipt evidence. Enter your name and a meaningful note when recording a monthly review. Reviews are append-only, require an active statement, and are marked outdated when the month’s evidence changes. A review can document exceptions without resolving them; exceptions remain visible in the overview. The reviewer name is an audit label in the shared workspace, not a separately verified personal login.

Month detail places the selected period and review state first, followed by monthly totals, receipt coverage, items to check, retained source statements, and the bank and receipt evidence lists. The period selector has optional controls for an unlisted month or another currency. Filters apply to the evidence lists; the totals and export always cover the entire period. Spending prompts and record-control guidance can be expanded below the evidence.

Opening a receipt from Monthly Close keeps the month, currency, bank-source filter and exceptions-only setting. Use **Back to Monthly Close** to return to that same view. Payment-status history is available both beside the accepted receipt and in the original receipt detail.

Possible matches between a receipt and a debit in neighboring months are shown as **inspection hints** only when the amount, date and vendor words support an unambiguous candidate. They do not create a paid status or change the bank and receipt totals. Compare the original records before recording any payment follow-up.

## PDF input and confirmation

PDF is the primary UI path. Statement PDFs are limited to 10 MB and 30 pages and are parsed in a bounded worker. Embedded text is preferred; only scanned pages use the configured OCR engine. Encrypted PDFs accept a request-only password that is never persisted, logged, or sent to the AI gateway.

The default parser is deterministic and private to the application. An unfamiliar layout fails closed. The user may then either use the CSV fallback or explicitly enable the separate statement AI fallback. Before that optional gateway call, Ledgerly masks obvious account and card numbers; company names, counterparties and transaction descriptions can still be present, so the UI requires an informed opt-in and warns that credits may be consumed. Product owners can cap this separate response with `STATEMENT_LLM_MAX_OUTPUT_TOKENS` without changing receipt extraction limits.

Every PDF produces a preview before import. The server binds the exact file hash and exact normalized preview to a 30-minute HMAC confirmation token. Browser-side changes, a different file, expiry, or replay after a successful import cannot silently create another statement. The user must inspect the debit rows and confirm the evidence. Opening balance plus credits less debits is compared with closing balance when both are available; a mismatch blocks import. The preview shows opening balance, total credits, debits, calculated closing balance, statement closing balance and difference so the operator can identify a misread row. Missing balances remain a visible warning rather than a fabricated validation result. AI extraction does not override a failed balance check.

Unconfirmed files are not retained. After confirmation, the original PDF, self-reported importer name, extraction method, masked metadata and validation result are stored with the normalized transactions. The PDF password is not stored. The importer name is an audit label under the shared application key, not verified identity.

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
- **Trade payable** and **Payment issue** are human-recorded audit events with actor, note, timestamp, and version. Trade payable may also include separate optional invoice due and planned payment dates. A planned date is a reminder, not proof of payment; only a matching bank debit can establish the app’s **Paid** status. Saving a new status appends an event and preserves earlier decisions.
- **Missing receipt** means a bank debit has no likely accepted receipt.
- **Duplicate transaction** identifies repeated date, amount, and normalized description values within imported statements for that month and currency.
- Existing receipt duplicate candidates remain visible as **Duplicate receipt**.

These exceptions are review signals, not proof of fraud. A person must inspect the source receipt, statement, and business context before escalating suspected fraud.

The monthly workspace lists every imported debit and every accepted receipt, not
only exceptions. A retained PDF or CSV can be opened in a read-only side panel
for cross-reference; receipts open in Ledgerly's existing evidence view. The
monthly Excel workbook includes Summary, Bank transactions, Receipts, Statement
sources and Payment audit sheets. Summary separates bank debits, accepted
receipt spend and **suggested** matched spend, and shows review state, reviewer
and note. Match coverage is `N/A` when there is no accepted spend. The
difference is bank debits **minus** accepted receipt spend; it is not a bank
balance or proof of payment. Duplicate debit rows stay unmatched until their
source evidence is resolved. Statement IDs and filenames connect each debit to
its retained file. Receipts include payable dates and linked debit IDs; Payment
audit lists every human-entered status change with actor, note and version.
Bank credits are excluded from this debit-focused export. Category and company
shares and all amounts remain in the selected original currency.

## Spending review prompts and Finance Copilot

The **Spending review prompts** below the receipt list are deterministic rules using accepted receipt totals for the selected month. They identify the largest category and vendor concentration, then suggest review actions. Ledgerly does not invent current market prices or claim a supplier is cheaper without verified quotes.

The animated receipt assistant at the bottom right opens a read-only Finance Copilot panel. In the overview, choose the period to discuss; in month detail, it uses that selected period. Quick actions and suggested questions only call the assistant when you submit them. It can explain recorded exceptions, prepare a close brief, and answer questions scoped to the month. Its result is advisory and cannot change statuses, import statements, or execute payments. Receipt references identified in the current month can be opened directly from the response. Close the panel with its close button or Escape; reduced-motion preferences stop the mascot animation.

## Singapore controls

The workflow preserves original receipt evidence, confirmed source statement PDFs or CSVs, review and amendment history, payment follow-up events, and monthly exports. This supports record keeping and accountability but does not certify legal or tax compliance.

- [IRAS record keeping requirements](https://www.iras.gov.sg/taxes/corporate-income-tax/basics-of-corporate-income-tax/record-keeping-requirements) state that companies must retain source documents, accounting records, and bank statements for at least five years from the relevant Year of Assessment.
- [PDPC data protection obligations](https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act/data-protection-obligations) remain the organisation's responsibility, including appropriate protection, access, and retention practices.
- [CPF Board guidance on payments attracting CPF](https://www.cpf.gov.sg/employer/employer-obligations/what-payments-attract-cpf-contributions) distinguishes qualifying official-purpose reimbursements from wages. Finance or HR must review the facts; receipt classification alone cannot decide CPF treatment.

Back up the SQLite database and retained receipt files as one evidence set. Restrict the shared API key to trusted staff and devices.

## Default reporting currency

The dashboard lets the workspace choose SGD, MYR, USD, EUR, GBP, or AUD as its default reporting currency. Accepted totals, category concentration, and the 12-month trend can then be viewed as one consolidated management estimate.

Conversion uses the latest available [European Central Bank reference-rate snapshot](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html), cached for 12 hours. The dashboard shows the rate date, source, and whether a cached fallback was used. If the current fetch fails, a snapshot older than seven days is rejected and Ledgerly shows native totals instead of a partial or misleading conversion. Original receipt and bank-statement amounts are never overwritten.

ECB states that its rates are normally updated each working day, are published for information purposes, and are not intended as transaction rates. Ledgerly therefore uses latest-rate conversion only for live management comparisons. Receipt-to-bank matching continues in the original currency.

For formal accounting reports, choose and document a stable policy with the accountant:

- transaction-date rates for individual transactions;
- a monthly average where permitted and volatility is not material; or
- a locked month-end closing rate for period-end balance translation.

Historical reports should store the applied rate snapshot so they do not change when a later rate is published. Automated locked-period translation is a future workflow; the current Excel reconciliation remains in its selected original currency.
