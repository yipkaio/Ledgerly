# Ledgerly v0.1.0

Initial tagged release of the Ledgerly single-bookkeeper MVP.

## Included

- Web and owner-only Telegram receipt intake, with OCR, structured extraction,
  vendor lookup, category suggestions and a confidence gate.
- Human review of retained originals; audit history, amendment, void and
  recoverable deletion workflows.
- Receipt history, date-range reporting and Excel exports with original-currency
  totals and a separate converted management view.
- Monthly close with bank PDF or normalized CSV import, retained statement
  sources, deterministic reconciliation, payment follow-up, human monthly review
  and whole-month Excel exports.
- Read-only Finance Copilot explanations scoped to the selected month's evidence.
- Local Docker Compose deployment and a production overlay with Caddy HTTPS and
  single-bookkeeper Firebase authentication.

## Before updating an existing deployment

Back up the SQLite database **and** retained uploads together, and keep an
off-instance copy. The application migrates supported databases to schema v9 on
first use; an older image cannot read the upgraded database. See the
[backup and rollback instructions](docker.md) and
[release checks](demo-readiness.md).

The GitHub repository is now `yipkaio/Ledgerly`. Fresh checkouts use
`https://github.com/yipkaio/Ledgerly.git`; existing directories are not renamed.
The Docker Compose project remains `expense-agent` to preserve its named volumes.

## Scope and limits

Ledgerly is designed for one controlled bookkeeper. `AUTO_FILED` is an internal
classification decision, not a human approval or external accounting posting.
Likely bank matches and Copilot answers require evidence review; neither proves
payment. PDF parsing depends on statement layout, and the optional AI statement
fallback requires explicit consent. See [security and MVP limitations](security.md).
