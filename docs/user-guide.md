# Ledgerly user guide

This guide walks through the implemented MVP using synthetic demonstration data.
Screenshots containing an account email have been redacted. Some images show
earlier interface states or separate demo runs; compare amounts only within the
example identified in its caption. The examples show workflow states, not
evidence that an external payment or accounting entry occurred.

## Access and navigation

The deployed page uses the pre-approved bookkeeper email/password account;
local development can use an app key. The top navigation includes **Main
dashboard**, **Monthly close**, **Upload receipt**, **Pending reviews**,
**Receipt history**, and **Deleted receipts**. The dashboard reports dated
accepted spend; Monthly close compares accepted receipts with bank evidence.

## Receipt intake and review

### Upload and triage

![Upload a receipt](assets/screenshots/153529.png)

Upload a JPEG, PNG or bounded PDF through the web workspace. Telegram receipts
reach the same authenticated backend through the OpenClaw relay.

![Pending reviews](assets/screenshots/153645.png)

Receipts with uncertain extraction, classification or duplicate evidence enter
the review queue. Open the retained source before deciding.

### Telegram examples

In one synthetic demo, the user sent a paid Grab receipt and its business
purpose in the same Telegram message. The reply reported **20 September 2026**,
**SGD 20.40**, **Travel and Transport**, **95% confidence** and `AUTO_FILED`.
That decision means no pending human review for this upload; it does not prove
human approval, a bank payment or an external accounting entry.

In a separate Dell example, the reply reported `REVIEW_QUEUE`, **18 September
2026**, **SGD 2,180.00**, **Office Supplies** and **85% confidence**, noting a
missing business purpose and the high-value purchase. The upload succeeded
and needs a decision in **Pending reviews**. Check the retained source and
business context before deciding. This Telegram capture is a separate run
from the accepted Dell record shown in the review and Monthly Close examples.

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
missing periods show zero recorded spend, and you can inspect points and exact
values. **Open receipt history** opens all receipts, while **View this date
range** carries dates and accepted statuses into history. Reporting currency conversion does
not alter original receipt amounts. Undated accepted receipts remain in history
but are not included in dated reporting.

## Receipt history and Excel export

To export dated accepted spend, choose **View this date range** on the dashboard.
Receipt history opens with the inclusive receipt dates and **Auto Filed**,
**Approved** and **Amended** already selected. Change search, category, status,
currency or dates and choose **Apply filters** before exporting. **Export filtered**
includes matching records on every page, up to 1,000. It never adds unlike
currencies together: the separate six-receipt demo has four SGD receipts
totalling SGD 3,340.85 and two MYR receipts totalling MYR 38.80.

To export specific records, check their rows and choose **Export selected**
(1–500 IDs). Selection survives pagination and resets when filters change. The
separate three-receipt example totals SGD 2,376.20. Both workbooks contain an
**Overview**, **Receipts**, **Line items**, and **Review audit** sheet; only
accepted records contribute to accepted spend. Deleted and voided receipts
are excluded from filtered exports and rejected if explicitly selected.
See [history and export rules](export.md).

## Deleted receipts and restoration

Use **Deleted receipts** to see recoverable records, restore deadlines and
authenticated previews. **Open** displays the retained original and lifecycle
events. **Restore receipt** is available within 30 days, subject to duplicate
checks and optimistic version control. Deletion excludes the receipt from
ordinary history, totals and exports while it is recoverable. Accepted receipts
use **Void receipt** instead; voiding is a distinct audited action and cannot
be undone with Restore. See [receipt lifecycle](receipt-lifecycle.md).

## Monthly close

Start in **Overview** to check all recorded periods across years. Months with accepted receipts appear even when you have not imported a bank statement. Use **Needs attention only** to focus on missing statements, exceptions and outdated reviews. Open a period for its original-currency reconciliation. A month is shown as reviewed only after you record the reviewer and note; evidence changes flag the review as outdated. Reviewing a month does not automatically resolve its exceptions.

Month detail first shows the period, review state, whole-month totals and
receipt coverage. **All months** returns to Overview; **Period in view**
switches recorded months, and **Jump to evidence** moves down the same page.
The newer four-debit September demo has SGD 3,340.85 in accepted receipts and
bank debits, but a past review can still be outdated after evidence changes.
The statement preview shown below comes from an earlier, separate two-debit
SGD 252.88 test.

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

In the current interface, **Source statements** offers **View source**,
**Download**, **Remove** and **Removed statements → Restore**. Removal excludes
an incorrect import from active matches and totals, preserves its original and
audit record, and may make a monthly review outdated. Evidence-list filters
such as **Bank source** and **Show items needing attention only** do not change
whole-month totals or the export.

### Resolve exceptions

![Matched debits and receipts](assets/screenshots/172159.png)

Harbour Cafe and Metrofleet are matched and paid. Dell remains `No Bank Match`.
That status alone does not prove an unpaid invoice, a failed payment or fraud.
Likely bank matches also require source inspection; a displayed **Paid** match
is not independent proof of settlement. Neighboring-month candidates remain
inspection hints. **Open receipt** and **Back to Monthly Close** preserve the
selected month, currency and evidence filters.

![Finance Copilot follow-up](assets/screenshots/172230.png)

Finance Copilot prioritises the SGD 2,180 gap and explains evidence and limits.
Its output is advisory and does not execute a change. In model context, 218,000
cents represents SGD 2,180.
The current interface opens Copilot using the animated receipt assistant at the lower
right of Monthly Close; this screenshot shows the earlier full-width presentation.
Choose **Explain exceptions**, **Build close brief**, a suggested question or
your own question about the selected month. The older September example with
one exception and 10% matched is a different demo state from the fully matched
September period described above.

![Unsaved payable dialog](assets/screenshots/172250.png)

The `Trade payable` option is selected, but the reviewer and evidence fields are
blank. This is an unsaved dialog—not proof that a payable was recorded. Resolve
the conflict between the receipt's `Card - paid` label and the missing bank match
before saving a payment follow-up.
The current dialog also supports optional invoice due and planned payment dates for
Trade payable. Each saved change appears in the receipt’s payment-status history,
and **Back to Monthly Close** returns to the month and filters you were reviewing.

![Retained statement source](assets/screenshots/172704.png)

The synthetic September statement remains available for cross-checking imported
values.

After inspecting all evidence, choose **Mark reviewed** or **Review again**,
enter a reviewer and meaningful note, and confirm the evidence check. A review
event documents the month without changing any receipt or bank transaction;
new evidence can make it outdated. **Export month** produces whole-period
Summary, Bank transactions, Receipts, Statement sources and Payment audit sheets.
Suggested matches remain hints, and evidence-list filters do not limit export rows.

## Complete screenshot inventory

The repository retains the earlier privacy-reviewed demonstration screenshots in
[`assets/screenshots`](assets/screenshots/). The separate, self-contained
visual preview also includes newer dashboard, Telegram, export, deleted-receipt
and Monthly Close captures. These show distinct moments and test runs; retain
their captions when interpreting totals or status.

## Interpretation limits

- AI agents extract, recommend or explain; they do not approve, pay or post.
- PDF parsing is layout-dependent. Use normalized CSV when a bank PDF cannot be
  validated safely.
- Optional AI statement extraction requires consent; an invalid deterministic
  preview does not currently trigger an automatic AI retry.
- `No Bank Match` is an exception signal, not a payable determination.
- Screenshots show synthetic demo states and may represent different points in the
  workflow.
