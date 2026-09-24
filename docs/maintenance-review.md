# Code quality and maintainability review

Code review performed against `main` at `37cab84` (23 September 2026). Scope: tracked
backend modules and routes, React components and API client, runtime manifests,
tests, integrations, deployment files, screenshots and Markdown documentation.
This is a historical static and test-backed review, not a production query
profile or a verification of the current deployment. Documentation and screenshot
inventory were checked again on 24 September 2026 against `c239d6e`.

## Cleanup completed

| Finding and evidence | Why it was unnecessary | Impact of cleanup | Risk addressed |
| --- | --- | --- | --- |
| `app/classification.py:lookup_vendor_category` was referenced only by `tests/test_classification.py`; uploads call `ReceiptStore.lookup_vendor` against persisted mappings. | It duplicated the initial seed dictionary as a second, inactive lookup path. | One fewer production helper and a test of the actual database-backed lookup, including normalization and an unmatched vendor. | Moved the assertions to `tests/test_database.py`; changing a saved vendor mapping must continue to affect uploads. |
| `app/main.py` imported `monthly_reconciliation` and `OCRResult` without using them. | They added dead names at the API entry point. | Removes two misleading imports; no runtime behavior change. | Confirmed neither import was a test monkeypatch target. |
| `monthly_reconciliation` called `_latest_payment_states` to scan latest payment events across the whole database, then queried all events again for current-month receipt IDs. | The second query already returns current-month events ordered newest first. | Removes a database-wide query and its helper on each monthly detail/overview read. | The first event remains the effective status, and all events remain in history. Existing reconciliation tests cover the behavior. |
| Root README had repeated status and implementation blocks, a schema-v8 claim and later appended schema-v9 notes. Some feature docs described old sign-in, export sheets and dashboard periods. | Conflicting instructions made the current workflow hard to follow. | Short entry point, separate developer setup, refreshed user guide and corrected cross-links. | Historical screenshots are identified as earlier or separate examples; migration and backup instructions still point to the operational docs. |

## Findings to handle in focused changes

| Finding | Why simplify | Estimated impact | Risk before deletion or rewrite |
| --- | --- | --- | --- |
| Three effective-receipt SQL projections live in `app/history.py`, `app/dashboard.py` and `app/statements.py`. They repeat amendment/review precedence and lifecycle filtering. | A rule change must be made consistently in several places. | Medium: one shared, tested projection could reduce drift and make category/status changes easier. | Their outputs differ: dashboard aggregates, history includes voided/deleted states, reconciliation only accepts active receipts. Preserve those semantics and benchmark SQLite query plans before consolidating. |
| `list_periods` in `app/statements.py` calls `monthly_reconciliation` and `period_review` for each distinct month/currency; each call opens further SQLite reads and builds adjacent-month hints. | Overview work grows with the number of periods even though it displays compact counts. | Potentially high latency improvement for large histories; no measured production figure yet. | Review fingerprints, duplicates and exceptions must stay identical. Profile realistic month counts, then calculate overview aggregates in bulk with regression fixtures. |
| `app/main.py` (over 1,100 lines), `app/statements.py` (over 1,000) and `frontend/src/App.tsx` (over 1,100) mix several distinct workflows. | Edits require navigating unrelated branches and increase review effort. | Medium maintainability gain from extracting route groups, statement import/reconciliation/export services, and workspace views. | FastAPI dependencies, authorization, React state, back-navigation and side effects can regress. Move one bounded workflow at a time with behavior checks. |
| Receipt detail in `app/database.py:get` performs several separate, indexed reads for classification, review, latest amendment, audit events and payment history. | Some joins or bulk reads may reduce round trips. | Low for one detail view; potentially useful after measurement. | The queries return different ordered histories and share one SQLite read snapshot. Keep the audit shape and ordering; do not collapse them just to reduce a query count. |
| README used to carry an illustrative one-receipt OCR comparison and long gateway details alongside the quick start. | It buried setup under repeated status text. | Easier onboarding after moving details to `docs/setup.md`. | The comparison is not a benchmark; preserve that qualification and the Paddle CPU pin. |
| The reviewed repository had 79 screenshot assets: 39 linked from the illustrated guide and 40 older assets in the parent screenshot directory. | Older captures can be confused with current screens if linked without a date. | Potential reduction in repository size and reader confusion after a separate review. | The guide distinguishes current views from earlier demo runs. The README now links a dated guide screenshot; review older assets individually before deleting historical evidence. |

## Inventory and deletion decisions

- **UI components:** Every `.tsx` component under `frontend/src/components`,
  including the local UI primitives, has a source import or a runtime entry point.
  There is no supported deletion of an entire UI component at this revision.
- **Routes and AI services:** Receipt, history, lifecycle, export, reconciliation
  and `/ai` routes have active callers or API contracts. No unused public route
  was verified. A route without a button may still be used by the Telegram
  integration or an external authenticated client.
- **Dependencies:** Runtime imports/build setup account for the declared Python
  and frontend packages reviewed. The OCR extra is optional by design. No
  dependency removal is supported by this pass.
- **Legacy and migrations:** Old schema steps and direct CSV import remain
  necessary for persisted databases and API compatibility. Do not delete them
  without a supported-version policy, a migration rehearsal and an explicit
  deprecation plan.
- **Tests and scripts:** Existing tests cover sensitive review, reconciliation,
  migration, export and authentication behavior. The container smoke script
  and Telegram/OpenClaw integration are connected to deployment guidance.

## Recommended order

1. The dead-code and payment-query cleanup landed with the documentation changes
   and backend/frontend gates in the earlier review.
2. Measure the Monthly Close overview with realistic period counts. Refactor its
   per-period queries only with a known baseline and identical fingerprints.
3. Extract a shared effective-receipt projection after specifying history,
   dashboard and reconciliation differences in tests.
4. Split large files by workflow, keeping their public API and navigation
   behavior stable; remove screenshot assets only after inventory review.
5. Re-run the release checklist on a disposable database and manually check
   a fresh Monthly Close export, back-navigation and dashboard date range
   before a production deployment. Do not use an older app image after the
   schema-v9 upgrade.
