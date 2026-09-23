# Documentation guide

Start here when operating, reviewing or demonstrating Ledgerly. The root
[`README.md`](../README.md) is the product overview and local quick start; the
documents below contain the detailed contracts and operating procedures.

## Understand the system

- [Architecture and data flow](architecture.md) — receipt workflow, trust
  boundaries, deployed AWS topology and component responsibilities.
- [Illustrated user guide](user-guide.md) — privacy-reviewed product walkthrough
  covering review, audit, reporting and monthly close.
- [AI agent architecture](ai-agents.md) — bounded agent capabilities, schemas,
  authority limits and safe fallbacks.
- [Security model](security.md) — authentication, secrets, network exposure,
  sensitive data, backups and accepted MVP limitations.
- [Workflow roadmap](workflow-roadmap.md) — product decisions and remaining
  usability priorities.
- [Code health review](maintenance-review.md) — verified cleanup, impacts,
  deletion risks and the next maintenance steps.

## Deploy and operate

- [Docker setup](docker.md) — local containers, persistent volumes, checks,
  backup basics and image rollback.
- [Developer setup](setup.md) — Windows PowerShell, OCR, gateway and test commands.
- [Authentication and production deployment](authentication.md) — Firebase,
  hybrid authentication, Caddy HTTPS and Lightsail verification.
- [Telegram and OpenClaw](telegram-openclaw.md) — owner-only Telegram intake,
  secret handling and gateway operation.
- [Demo readiness](demo-readiness.md) — release gate, acceptance flow and metrics.

## Use and verify features

- [Receipt workspace](frontend.md)
- [Human review](reviews.md)
- [Receipt lifecycle](receipt-lifecycle.md)
- [Reprocessing and reconciliation](reprocessing.md)
- [Monthly bank reconciliation](monthly-reconciliation.md)
- [History and Excel export](export.md)
- [PDF receipt ingestion](pdf.md)

## Documentation rules

- Keep operational commands in the deployment document that owns them instead
  of copying divergent versions across multiple files.
- Do not place real keys, tokens, UIDs, email addresses, receipt data or bank
  data in documentation or examples.
- Update `architecture.md` whenever an external service, public port, trust
  boundary or persistent store changes.
- Update `demo-readiness.md` whenever a release-gating test changes.
