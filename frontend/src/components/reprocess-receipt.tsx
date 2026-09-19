import { useRef, useState } from "react";
import { LoaderCircle, RefreshCw } from "lucide-react";
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
import { Reconciliation } from "@/components/reconciliation";
import { ApiError, message, request } from "@/lib/api";
import type { Receipt, ReprocessAttempt } from "@/lib/api";
import { useClock } from "@/lib/use-clock";

export function ReprocessReceipt({
  receipt,
  token,
  disabled,
  saved,
  onUseDraft,
}: {
  receipt: Receipt;
  token: string;
  disabled: boolean;
  saved: () => void;
  onUseDraft: (draft: ReprocessAttempt) => void;
}) {
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [uncertain, setUncertain] = useState(false);
  const attempt = useRef<object | null>(null),
    submitting = useRef(false);
  const now = useClock();
  const history = receipt.reprocessing || [];
  const running = history.some(
    (item) =>
      item.status === "RUNNING" && new Date(item.expires_at).getTime() > now,
  );
  const eligible =
    (!receipt.lifecycle_state || receipt.lifecycle_state === "ACTIVE") &&
    receipt.processing_status !== "PROCESSING" &&
    receipt.review?.decision !== "REJECTED";
  const latest = history[0];
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    attempt.current ||= {
      request_id: crypto.randomUUID(),
      expected_record_version: receipt.record_version || 0,
      expected_lifecycle_version: receipt.lifecycle_version || 0,
      reviewer: name.trim(),
      reason: reason.trim(),
    };
    try {
      await request<ReprocessAttempt>(
        `/receipts/${receipt.receipt_id}/reprocess`,
        token,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(attempt.current),
          timeoutMs: 210000,
        },
      );
      attempt.current = null;
      setUncertain(false);
      setOpen(false);
      saved();
    } catch (e) {
      setError(message(e));
      if (e instanceof ApiError && e.status < 500) {
        attempt.current = null;
        setUncertain(false);
      } else setUncertain(true);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="panel p-5" aria-label="Receipt reprocessing">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="font-semibold">Reprocess receipt</h2>
          <p className="muted mt-1">
            Create a fresh extraction draft from saved OCR. Original evidence
            and accepted values stay unchanged until you review and save a
            decision.
          </p>
        </div>
        {eligible && (
          <Button
            variant="outline"
            disabled={disabled || running || !receipt.ocr_text?.trim()}
            onClick={() => {
              setOpen(true);
              setName("");
              setReason("");
              setError("");
            }}
          >
            <RefreshCw />
            Reprocess receipt
          </Button>
        )}
      </div>
      {eligible && !receipt.ocr_text?.trim() && (
        <p className="muted mt-3">
          No saved OCR text is available. Upload a new readable receipt to run
          OCR again.
        </p>
      )}
      {latest && (
        <div className="mt-4 space-y-3 border-t pt-4">
          <p className="text-sm font-medium">
            Latest attempt ·{" "}
            {latest.status === "SUCCEEDED"
              ? "Draft ready for review"
              : latest.status === "RUNNING"
                ? running
                  ? "Extracting…"
                  : "Interrupted — start a new attempt"
                : latest.status === "SUPERSEDED"
                  ? "Receipt changed during extraction; draft not applied"
                  : "Extraction failed"}
          </p>
          <p className="muted">
            {new Date(latest.started_at).toLocaleString()} · {latest.reviewer}{" "}
            (self-reported)
          </p>
          <p className="break-words text-sm">{latest.reason}</p>
          {latest.error && <Notice variant="warning">{latest.error}</Notice>}
          {latest.status === "SUCCEEDED" && latest.extracted_data && (
            <>
              <Reconciliation data={latest.extracted_data} />
              {eligible && (
                <Button disabled={disabled} onClick={() => onUseDraft(latest)}>
                  Use draft for review
                </Button>
              )}
              <p className="muted">
                Using a draft does not save it. Check every field and the
                category against the original receipt before approving or
                amending.
              </p>
            </>
          )}
          {latest.status === "RUNNING" && (
            <Button variant="outline" disabled={disabled} onClick={saved}>
              Check progress
            </Button>
          )}
        </div>
      )}
      {history.length > 1 && (
        <details className="mt-4 text-sm">
          <summary className="font-medium">
            Earlier extraction attempts ({history.length - 1})
          </summary>
          <ol className="mt-3 space-y-3">
            {history.slice(1).map((item) => (
              <li key={item.request_id} className="border-l-2 pl-3">
                <p>
                  {new Date(item.started_at).toLocaleString()} · {item.status} ·{" "}
                  {item.reviewer}
                </p>
                <p className="muted break-words">{item.reason}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy && !uncertain) setOpen(value);
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
            <DialogTitle>Reprocess this receipt?</DialogTitle>
            <DialogDescription>
              This makes one new AI extraction request and may consume credits.
              It uses saved OCR text, not a new image scan. No existing
              evidence, category or approved amount is overwritten.
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submit}>
            <div>
              <label className="field-label" htmlFor="reprocess-name">
                Your name
              </label>
              <Input
                id="reprocess-name"
                required
                maxLength={100}
                disabled={busy || uncertain}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div>
              <label className="field-label" htmlFor="reprocess-reason">
                Reason for reprocessing
              </label>
              <Textarea
                id="reprocess-reason"
                required
                minLength={10}
                maxLength={2000}
                disabled={busy || uncertain}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="For example: extract the receipt discount added in the latest update"
              />
            </div>
            {error && <Notice variant="destructive">{error}</Notice>}
            {uncertain && (
              <Notice variant="warning">
                Check the same request to retrieve its status without starting
                another paid extraction.
              </Notice>
            )}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setOpen(false);
                  if (uncertain) saved();
                  attempt.current = null;
                  setUncertain(false);
                }}
              >
                Cancel
              </Button>
              <Button
                disabled={busy || !name.trim() || reason.trim().length < 10}
              >
                {busy && <LoaderCircle className="animate-spin" />}
                {busy
                  ? "Extracting…"
                  : uncertain
                    ? "Check same request"
                    : "Create extraction draft"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  );
}
