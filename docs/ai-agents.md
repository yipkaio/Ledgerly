# AI agent architecture

Ledgerly exposes three **logical** AI agents. They are bounded service
responsibilities, not autonomous accounting users and not nine independent model
processes.

## Authority model

| Agent | Capabilities | Authority |
|---|---|---|
| Document Intelligence | Receipt extraction and opt-in bank-statement extraction | Extract only |
| Classification and Compliance | Categorisation, vendor normalisation, deterministic control checks and review guidance | Recommend only |
| Finance Copilot | Reconciliation explanations, monthly-close briefs and scoped finance Q&A | Read only |

The database remains the source of truth. Arithmetic, exact duplicate detection,
vendor lookup, confidence gating, reconciliation matching and lifecycle eligibility
remain deterministic. AI cannot approve or reject a transaction, change payment
status, post a journal entry, initiate a payment or declare fraud.

## Package layout

- `app/agents/document_intelligence.py` provides one facade over the existing
  receipt and statement extractors.
- `app/agents/compliance.py` performs deterministic evidence checks before it
  asks the model for optional review guidance.
- `app/agents/copilot.py` accepts only bounded reconciliation context and
  produces explanations, briefs or evidence-linked answers.
- `app/agents/gateway.py` centralises strict JSON validation, response limits,
  timeouts, prompt versions, SHA-256 input fingerprints and a small in-process
  cache.
- `app/agents/router.py` contains the authenticated, on-demand HTTP boundary.

## Endpoints

All endpoints require `X-API-Key`.

- `GET /ai/agents` describes the capabilities and authority of every agent.
- `POST /ai/receipts/{receipt_id}/review-assistance` runs deterministic control
  checks and returns optional human-review guidance.
- `POST /ai/reconciliation/explain` explains exceptions already produced by
  deterministic reconciliation.
- `POST /ai/monthly-close/brief` prepares a close brief and checklist for one
  month and currency.
- `POST /ai/copilot/ask` answers one read-only question within a supplied month
  and currency.

Example request body for the reconciliation explanation and close brief:

```json
{
  "month": "2026-09",
  "currency": "SGD"
}
```

Example Finance Copilot request:

```json
{
  "month": "2026-09",
  "currency": "SGD",
  "question": "Which unmatched debits need receipt evidence?"
}
```

## Data minimisation and prompt-injection handling

The Finance Copilot receives the existing reconciliation result, not the retained
PDF/CSV or OCR text. Source bytes, file paths, passwords, API keys and full account
identifiers are removed. Lists, strings, nesting and total prompt size are bounded.

Every prompt labels supplied records as untrusted data and tells the model not to
follow instructions found inside them. Every response is validated against a
task-specific Pydantic schema. Invalid, truncated, oversized, timed-out or
unavailable responses fail safely and never change workspace state.

## Cost and audit controls

Calls are on demand. Identical model/task/prompt/input requests are cached for 15
minutes in the current process. Each response includes:

- request ID;
- task and prompt version;
- model;
- SHA-256 fingerprint of the canonical input;
- cache status; and
- creation timestamp.

The fingerprint supports comparison without returning hidden prompts or sensitive
source documents. The cache is deliberately non-persistent and is cleared on
process restart.

## Human workflow

1. Upload and extract documents.
2. Apply deterministic vendor lookup, checks and confidence gating.
3. Auto-file only eligible high-confidence receipts; route uncertainty to review.
4. Match accepted receipts to bank debits deterministically.
5. Request an AI explanation, close brief or scoped answer when useful.
6. Verify original evidence and make every approval or correction through the
   existing audited human workflow.

AI output is advisory and must not be treated as evidence that a review occurred.
