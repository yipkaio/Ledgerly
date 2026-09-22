# Demo-readiness checklist

Use this list after every production deployment and before the hackathon demo.

## Release gate

- Backend tests pass in GitHub Actions.
- Frontend lint, unit tests and production build pass.
- Docker health check becomes healthy.
- The current SQLite database and uploads have an off-instance backup.
- Only ports 22, 80 and 443 are public.
- HTTPS is valid and HTTP redirects to HTTPS.
- Firebase accepts only the configured bookkeeper UID.
- API documentation is disabled in production.
- No API key, Firebase token, receipt text or bank data appears in logs.
- The workflow and deployed topology still match
  [the architecture diagrams](architecture.md).
- The [security release checklist](security.md#before-every-production-release)
  is complete, including `main` branch protection.

## End-to-end acceptance

1. Upload a JPEG, PNG and bounded PDF receipt.
2. Confirm duplicate blocking and confidence routing.
3. Approve, amend and export selected receipts.
4. Import a CSV and a PDF bank statement.
5. Confirm deterministic matching and exception counts.
6. Check source preview, remove a wrong statement, then restore it.
7. Ask the Finance Copilot an in-scope question and an unrelated question.
8. Confirm the dashboard's default currency, custom date range, quick ranges and all-time total; open the matching accepted receipts in history.
9. Restart the containers and confirm records and evidence remain available.

## Demo metrics

Record the tested dataset size, field-extraction accuracy, classification accuracy,
auto-file percentage, Review Queue percentage, average processing time and LLM
calls per receipt. The current targets are at least 90% classification accuracy,
at least 70% automatic classification, no more than 30% human review, and total
shared infrastructure/API spend within US$100.

Do not widen the AI's authority to improve these numbers. Deterministic calculations,
matching and database writes remain authoritative, and uncertain results remain
human-reviewed.
