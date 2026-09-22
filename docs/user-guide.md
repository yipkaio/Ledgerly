# Ledgerly user guide

This guide walks through the implemented MVP using synthetic demonstration data.
Screenshots containing an account email have been redacted. The examples show
workflow states, not evidence that an external payment or accounting entry occurred.

## Receipt intake and review

### Upload and triage

![Upload a receipt](assets/screenshots/153529.png)

Upload a JPEG, PNG or bounded PDF through the web workspace. Telegram receipts
reach the same authenticated backend through the OpenClaw relay.

![Pending reviews](assets/screenshots/153645.png)

Receipts with uncertain extraction, classification or duplicate evidence enter
the review queue. Open the retained source before deciding.

### Check evidence and record a decision

![Original receipt and extracted fields](assets/screenshots/153818.png)

Compare the original receipt with the vendor, receipt number, date, currency,
amounts and payment information. Arithmetic checks support review but do not prove
business purpose or authenticity.

![Correctly annotated review confirmation](assets/screenshots/review-evidence-confirmation.svg)

Select the final category, enter the reviewer and reason, then explicitly confirm
that the original evidence was checked. AI assistance cannot approve for the
reviewer.

![Review confirmation](assets/screenshots/153955.png)

Approval or rejection records an auditable human decision. Accepted records use
amendment or void workflows rather than silent edits.

### Audit and correction

![Accepted receipt detail](assets/screenshots/154024.png)

The effective values remain visible beside the retained source. The displayed
Dell document says `Card - paid`; that label is not proof of an operating-account
bank match.

![Review audit](assets/screenshots/154030.png)

The audit records the outcome, reviewer, reason and evidence confirmation.

![Amendment comparison](assets/screenshots/154550.png)

An amendment creates a new effective version while preserving the earlier values
and source evidence.

## Dashboard and reporting

![Dashboard overview](assets/screenshots/154111.png)

This earlier screenshot shows the previous period selector. The current dashboard
places one receipt-date range beside the default reporting currency. Choose All time
(first to latest dated accepted receipt), latest month, latest three months,
latest receipt year, or enter start and end dates and select **Apply dates**.
The quick ranges end at the latest accepted receipt date. The same inclusive
range updates the accepted total, receipt count, chart and categories. Select
**View this date range** to open the matching accepted receipts in history.

![Period comparison](assets/screenshots/154133.png)

This earlier screenshot shows the previous comparison controls. The chart now uses
monthly points for ranges of up to 24 months and yearly points for longer ranges;
you can still inspect points and exact values. Reporting currency conversion does
not alter original receipt amounts. Undated accepted receipts remain in history
but are not included in dated reporting.

## Monthly close

Start in **Overview** to check all recorded periods across years. Months with accepted receipts appear even when you have not imported a bank statement. Use **Needs attention only** to focus on missing statements, exceptions and outdated reviews. Open a period for its original-currency reconciliation. A month is shown as reviewed only after you record the reviewer and note; evidence changes flag the review as outdated. Reviewing a month does not automatically resolve its exceptions.

### Import a statement

![Statement upload form](assets/screenshots/172119.png)

Choose a bank PDF or normalized CSV, month and currency. The email in this
privacy-reviewed screenshot is redacted. Deterministic PDF parsing is private by
default; optional AI fallback requires explicit consent, and a PDF password is
used only in memory for preview.

![Correctly annotated statement validation](assets/screenshots/statement-balance-validation.svg)

The preview contains two debit rows totalling SGD 252.88 and a passing balance
check. The balance panel explains opening balance + credits − debits versus the
statement closing balance, with the difference when they disagree. The reviewer
must compare every row with the source before import.

![Statement retained and totals updated](assets/screenshots/172146.png)

After import, the retained statement can be opened again. Bank debits and matched
paid both show SGD 252.88, with one receipt still needing attention. The email in
this screenshot is redacted.

### Resolve exceptions

![Matched debits and receipts](assets/screenshots/172159.png)

Harbour Cafe and Metrofleet are matched and paid. Dell remains `No Bank Match`.
That status alone does not prove an unpaid invoice, a failed payment or fraud.

![Finance Copilot follow-up](assets/screenshots/172230.png)

Finance Copilot prioritises the SGD 2,180 gap and explains evidence and limits.
Its output is advisory and does not execute a change. In model context, 218,000
cents represents SGD 2,180.

![Unsaved payable dialog](assets/screenshots/172250.png)

The `Trade payable` option is selected, but the reviewer and evidence fields are
blank. This is an unsaved dialog—not proof that a payable was recorded. Resolve
the conflict between the receipt's `Card - paid` label and the missing bank match
before saving a payment follow-up.

![Retained statement source](assets/screenshots/172704.png)

The synthetic September statement remains available for cross-checking imported
values.

## Complete screenshot inventory

The privacy-reviewed demonstration set contains 38 screenshots. The focused guide
above uses the most informative views; the full set is retained in
[`assets/screenshots`](assets/screenshots/) for traceable product review.

## Interpretation limits

- AI agents extract, recommend or explain; they do not approve, pay or post.
- PDF parsing is layout-dependent. Use normalized CSV when a bank PDF cannot be
  validated safely.
- Optional AI statement extraction requires consent; an invalid deterministic
  preview does not currently trigger an automatic AI retry.
- `No Bank Match` is an exception signal, not a payable determination.
- Screenshots show synthetic demo states and may represent different points in the
  workflow.
