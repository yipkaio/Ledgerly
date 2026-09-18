import { useRef, useState } from "react";
import {
  ArchiveRestore,
  Ban,
  Clock3,
  LoaderCircle,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Notice } from "@/components/feedback";
import { ApiError, message, request } from "@/lib/api";
import type { Receipt } from "@/lib/api";
import { useClock } from "@/lib/use-clock";

type Action = "DELETE" | "RESTORE" | "VOID";
const labels: Record<Action, string> = {
  DELETE: "Move to deleted receipts",
  RESTORE: "Restore receipt",
  VOID: "Void receipt",
};

export function ReceiptLifecycle({
  receipt,
  token,
  disabled,
  saved,
}: {
  receipt: Receipt;
  token: string;
  disabled: boolean;
  saved: () => void;
}) {
  const [action, setAction] = useState<Action | null>(null);
  const now = useClock();
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [stale, setStale] = useState(false);
  const attempt = useRef<object | null>(null);
  const submitting = useRef(false);
  const state = receipt.lifecycle_state || "ACTIVE";
  const accepted =
    !!receipt.amendment ||
    receipt.review?.decision === "APPROVED" ||
    (!receipt.review &&
      receipt.classification?.workflow_decision === "AUTO_FILED");
  const expired =
    !!receipt.purge_after && new Date(receipt.purge_after).getTime() <= now;
  const available: Action | null =
    state === "DELETED"
      ? expired
        ? null
        : "RESTORE"
      : state === "VOIDED" || receipt.processing_status === "PROCESSING"
        ? null
        : accepted
          ? "VOID"
          : "DELETE";
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!action || submitting.current || stale) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    const payload = attempt.current || {
      request_id: crypto.randomUUID(),
      action,
      expected_version: receipt.lifecycle_version || 0,
      expected_record_version: receipt.record_version || 0,
      reviewer: name.trim(),
      reason: reason.trim(),
    };
    attempt.current = payload;
    try {
      await request(`/receipts/${receipt.receipt_id}/lifecycle`, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setAction(null);
      setUncertain(false);
      attempt.current = null;
      saved();
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.status < 500) {
        attempt.current = null;
        setUncertain(false);
        setStale(e.status === 409);
      } else setUncertain(true);
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }
  return (
    <section className="panel overflow-hidden" aria-label="Receipt lifecycle">
      <div className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="rounded-xl bg-muted p-2.5" aria-hidden="true">
            {state === "DELETED" ? (
              <Clock3 className="size-5" />
            ) : state === "VOIDED" ? (
              <Ban className="size-5" />
            ) : (
              <ShieldCheck className="size-5" />
            )}
          </span>
          <div>
            <h2 className="font-semibold">
              {state === "DELETED"
                ? "In deleted receipts"
                : state === "VOIDED"
                  ? "Voided · evidence retained"
                  : accepted
                    ? "Finalized record protection"
                    : "Manage this receipt"}
            </h2>
            <p className="muted mt-1 max-w-2xl">
              {state === "DELETED"
                ? `${expired ? "Restore window ended. Awaiting automatic erasure." : "Restore before"} ${!expired && receipt.purge_after ? new Date(receipt.purge_after).toLocaleString() : ""}`
                : state === "VOIDED"
                  ? "Excluded from totals and exports. The original receipt and decision history remain read-only."
                  : accepted
                    ? "Cannot be deleted or rejected. Void an incorrect entry with a recorded reason."
                    : receipt.processing_status === "PROCESSING"
                      ? "Wait for processing to finish before managing this receipt."
                      : "Deleted receipts can be restored for 30 days, then are permanently erased."}
            </p>
          </div>
        </div>
        {available && (
          <Button
            variant="outline"
            disabled={disabled}
            onClick={() => {
              setAction(available);
              setName("");
              setReason("");
              setError("");
              setStale(false);
            }}
          >
            {available === "RESTORE" ? (
              <ArchiveRestore />
            ) : available === "VOID" ? (
              <Ban />
            ) : (
              <Trash2 />
            )}
            {labels[available]}
          </Button>
        )}
      </div>
      {!!receipt.lifecycle_events?.length && (
        <div className="border-t bg-muted/30 px-5 py-4">
          <h3 className="mb-3 text-sm font-semibold">Lifecycle history</h3>
          <ol className="space-y-4">
            {receipt.lifecycle_events.map((event) => (
              <li
                key={event.version}
                className="border-l-2 border-slate-300 pl-4 text-sm"
              >
                <p className="font-medium">
                  {event.action === "DELETE"
                    ? "Moved to deleted receipts"
                    : event.action === "VOID"
                      ? "Voided"
                      : "Restored"}{" "}
                  · {event.reviewer}
                </p>
                <p className="muted">
                  <time dateTime={event.occurred_at}>
                    {new Date(event.occurred_at).toLocaleString()}
                  </time>{" "}
                  · Self-reported identity
                </p>
                <p className="mt-1 break-words">{event.reason}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
      <Dialog
        open={!!action}
        onOpenChange={(open) => {
          if (!open && !busy && !uncertain) setAction(null);
        }}
      >
        <DialogContent
          onEscapeKeyDown={(event) => {
            if (busy || uncertain) event.preventDefault();
          }}
          onPointerDownOutside={(event) => {
            if (busy || uncertain) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>
              {action ? labels[action] : "Manage receipt"}
            </DialogTitle>
            <DialogDescription>
              {action === "DELETE"
                ? "This removes the receipt from active lists. You can restore it within 30 days; after that its data and files are permanently erased."
                : action === "VOID"
                  ? "This excludes the expense from totals and future exports. It cannot be undone here. The original evidence and audit history are retained."
                  : "Restore the previous workflow state. Restoration is blocked if an identical retained receipt already exists."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={submit} className="space-y-4">
            <div className="rounded-lg bg-muted p-3 text-sm font-medium">
              {receipt.effective_data?.vendor ||
                receipt.extracted_data?.vendor ||
                "Receipt"}
              <span className="muted mt-1 block font-mono">
                {receipt.receipt_id.slice(0, 8)}
              </span>
            </div>
            <div>
              <label htmlFor="lifecycle-name" className="field-label">
                Your name
              </label>
              <Input
                id="lifecycle-name"
                autoComplete="off"
                required
                maxLength={100}
                value={name}
                disabled={busy || uncertain || stale}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="lifecycle-reason" className="field-label">
                Reason
              </label>
              <Textarea
                id="lifecycle-reason"
                required
                minLength={10}
                maxLength={2000}
                value={reason}
                disabled={busy || uncertain || stale}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Explain why this change is needed"
              />
              <p className="muted mt-1">
                At least 10 characters. Recorded with your self-reported name.
              </p>
            </div>
            {error && <Notice variant="destructive">{error}</Notice>}
            {uncertain && (
              <Notice variant="warning">
                The response is uncertain. Retry uses the same request, so the
                action will not be duplicated.
              </Notice>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setAction(null);
                  attempt.current = null;
                  if (uncertain || stale) saved();
                  setUncertain(false);
                }}
              >
                {uncertain || stale ? "Reload saved record" : "Cancel"}
              </Button>
              <Button
                type="submit"
                variant={action === "RESTORE" ? "default" : "destructive"}
                disabled={
                  busy ||
                  stale ||
                  name.trim().length === 0 ||
                  reason.trim().length < 10
                }
              >
                {busy && <LoaderCircle className="animate-spin" />}
                {busy
                  ? "Saving…"
                  : uncertain
                    ? "Retry same action"
                    : action
                      ? labels[action]
                      : "Confirm"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
