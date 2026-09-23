# Undo, extraction drafts and reconciliation

These are separate reviewer actions: Undo deletion restores an eligible
record, Reprocess creates a draft from retained OCR, and the totals panel
checks arithmetic. None silently approves or posts an expense.

After deletion, **Undo deletion** restores the record with one click, retaining a restore audit event under the same self-reported name. It uses the normal restore rules: stale changes, expiry and an identical retained receipt prevent restoration. An uncertain response retries the same request UUID. The banner lasts while the receipt detail remains mounted; after leaving, restore from Deleted receipts within 30 days. Voiding cannot be undone through this action.

**Reprocess receipt** runs extraction against saved OCR text. It does not rerun OCR, classification, upload, or payment processing. The confirmation explains the possible AI cost. A name and reason are required. Active pending, failed, approved, auto-filed and amended records with saved OCR are eligible; processing, deleted, voided and rejected records are not. If original OCR was unavailable, upload a new readable file instead (or delete a failed duplicate first).

Each attempt has a durable UUID, start time, model identifier, self-reported reviewer, reason, status and result. Identical retries return the saved result/status without repeating the paid request. Only one extraction can run per receipt. Calls time out after 180 seconds. An interrupted process retains its running marker until its ten-minute lease expires; a new attempt may then begin. The same interrupted UUID is never automatically rerun. Errors shown to users exclude upstream diagnostics.

Successful results are **drafts**. Choose **Use draft for review**, compare every field with the original, confirm the category and save a review or amendment. Approval/amendment records link back to the draft UUID. No original extraction, OCR, previous decision or accepted value is overwritten by reprocessing. Failed receipts with a successful draft enter the review queue; their original error stays visible. Concurrent review, amendment, delete/restore or void makes an in-flight result superseded. Deleted receipt retention also purges extraction attempts after expiry; voided/accepted evidence remains retained.

The totals panel shows subtotal − receipt discount + tax + rounding, expected total, recorded total and difference. Values are compared in cents with a 0.02 tolerance. A provided before-rounding value is checked too. Missing subtotal, tax or total makes reconciliation incomplete. Absent optional discount/rounding contribute zero only in the display calculation; no field is changed. A match confirms arithmetic, not tax correctness, business purpose or receipt authenticity. Backend review validation remains authoritative.

Schema v5 adds the draft table without modifying existing evidence. Back up database and uploads together before deployment. Run `python -m pytest`; in frontend run `npm run build`, `npm run lint`, `npm run test:unit` (Node 22.6+; Node 24 recommended by Docker), and `npm test`. Browser coverage includes deletion Undo and draft loading/submission. Tests mock extraction and do not spend AI credits.
