import { useEffect, useRef, useState } from "react";
import { FileCheck2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, categories, message, request } from "@/lib/api";
import type {
  Extraction,
  Amendment,
  AmendmentRequest,
  LineItem,
  Receipt,
  Review,
  ReviewRequest,
} from "@/lib/api";
import { Notice, Status } from "@/components/feedback";

function Field({
  name,
  value,
  set,
  numeric = false,
  required = false,
  disabled = false,
  step = "0.01",
}: {
  name: string;
  value: string | number | null;
  set: (value: string | number | null) => void;
  numeric?: boolean;
  required?: boolean;
  disabled?: boolean;
  step?: string;
}) {
  const id = name.replaceAll(" ", "-").toLowerCase();
  return (
    <div>
      <label htmlFor={id} className="field-label">
        {name}
        {required && " *"}
      </label>
      <Input
        id={id}
        value={value ?? ""}
        type={numeric ? "number" : name === "Receipt date" ? "date" : "text"}
        step={numeric ? step : undefined}
        required={required}
        disabled={disabled}
        onChange={(e) =>
          set(
            e.target.value === ""
              ? null
              : numeric
                ? Number(e.target.value)
                : e.target.value,
          )
        }
      />
    </div>
  );
}
const blankLine: LineItem = {
  description: null,
  quantity: 1,
  unit_price: null,
  discount_percent: null,
  discount_amount: null,
  line_total: null,
};
export function ReceiptDetail({
  id,
  token,
  saved,
  onDirty,
}: {
  id: string;
  token: string;
  saved: () => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [receipt, setReceipt] = useState<Receipt | null>(null),
    [data, setData] = useState<Extraction | null>(null),
    [image, setImage] = useState(""),
    [imageError, setImageError] = useState(""),
    [error, setError] = useState(""),
    [audit, setAudit] = useState<Review[]>([]),
    [amendments, setAmendments] = useState<Amendment[]>([]),
    [revision, setRevision] = useState(0),
    [reviewer, setReviewer] = useState(""),
    [note, setNote] = useState(""),
    [category, setCategory] = useState(""),
    [evidence, setEvidence] = useState(false),
    [override, setOverride] = useState(""),
    [confirm, setConfirm] = useState<
      "APPROVED" | "REJECTED" | "AMENDMENT" | null
    >(null),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState<
      | { kind: "review"; payload: ReviewRequest }
      | { kind: "amendment"; payload: AmendmentRequest }
      | null
    >(null),
    [stale, setStale] = useState(false);
  const form = useRef<HTMLFormElement>(null),
    submitting = useRef(false),
    active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    let imageURL = "";
    // oxlint-disable-next-line react/set-state-in-effect -- Reset stale evidence for this cancellable API read.
    setError("");
    setReceipt(null);
    setImage("");
    setImageError("");
    setAudit([]);
    setAmendments([]);
    request<Receipt>(`/receipts/${id}`, token, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setReceipt(result);
        setData(structuredClone(result.effective_data || result.extracted_data));
        setCategory(result.effective_category || result.classification?.category || "");
        setPending(null);
        setStale(false);
        setEvidence(false);
        setReviewer("");
        setNote("");
        setOverride("");
        onDirty(false);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      });
    request<{ items: Review[] }>(`/receipts/${id}/reviews`, token, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setAudit(result.items);
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(`Audit could not be loaded: ${message(e)}`);
      });
    request<{ items: Amendment[] }>(`/receipts/${id}/amendments`, token, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!controller.signal.aborted) setAmendments(result.items);
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(`Amendment audit could not be loaded: ${message(e)}`);
      });
    fetch(`/receipts/${id}/image`, {
      headers: { "X-API-Key": token },
      cache: "no-store",
      signal: AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]),
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            "The original image is unavailable. Do not approve without checking the evidence.",
          );
        return response.blob();
      })
      .then((blob) => {
        if (!controller.signal.aborted) {
          imageURL = URL.createObjectURL(blob);
          setImage(imageURL);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setImageError(message(e));
      });
    return () => {
      controller.abort();
      if (imageURL) URL.revokeObjectURL(imageURL);
    };
  }, [id, token, revision, onDirty]);
  const reviewable =
    receipt?.processing_status === "REVIEW_QUEUE" && !receipt.review;
  const amendable =
    receipt?.processing_status === "COMPLETED" ||
    receipt?.review?.decision === "APPROVED" ||
    !!receipt?.amendment;
  const editable = reviewable || amendable;
  const locked = busy || !!pending || stale || !editable;
  async function submit(
    submission:
      | { kind: "review"; payload: ReviewRequest }
      | { kind: "amendment"; payload: AmendmentRequest },
  ) {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    setPending(submission);
    setConfirm(null);
    try {
      const path =
        submission.kind === "review"
          ? `/receipts/${id}/review`
          : `/receipts/${id}/amendments`;
      await request<Review | Amendment>(path, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submission.payload),
      });
      if (active.current) {
        saved();
        setRevision((n) => n + 1);
      }
    } catch (e) {
      if (active.current) {
        setError(message(e));
        if (e instanceof ApiError && e.status < 500) {
          setPending(null);
          if (e.status === 409) {
            setStale(true);
            setError(
              "The receipt or request changed. Reload the saved record before making another decision.",
            );
          }
        }
      }
    } finally {
      submitting.current = false;
      if (active.current) setBusy(false);
    }
  }
  function prepare(decision: "APPROVED" | "REJECTED" | "AMENDMENT") {
    if (decision !== "REJECTED" && !form.current?.reportValidity()) return;
    if (!reviewer.trim() || !note.trim() || !evidence) {
      setError(
        "Enter your name and a meaningful reason, and confirm that you checked the original receipt and purpose.",
      );
      return;
    }
    if (
      decision !== "REJECTED" &&
      (!data?.currency ||
        !categories.includes(category as (typeof categories)[number]))
    ) {
      setError("Choose a currency and an allowed category.");
      return;
    }
    setConfirm(decision);
  }
  function execute() {
    if (!confirm || !receipt) return;
    if (confirm === "AMENDMENT" && data) {
      const payload: AmendmentRequest = {
        request_id: crypto.randomUUID(),
        expected_version: receipt.record_version,
        reviewer: reviewer.trim(),
        reason: note.trim(),
        evidence_confirmed: true,
        final_data: structuredClone(data),
        category,
      };
      if (override.trim()) payload.override_reason = override.trim();
      void submit({ kind: "amendment", payload });
      return;
    }
    if (confirm === "AMENDMENT") return;
    const payload: ReviewRequest = {
      request_id: crypto.randomUUID(),
      expected_version: receipt.review_version,
      decision: confirm,
      reviewer: reviewer.trim(),
      note: note.trim(),
      evidence_confirmed: true,
    };
    if (confirm === "APPROVED" && data) {
      payload.corrected_data = structuredClone(data);
      payload.category = category;
      if (override.trim()) payload.override_reason = override.trim();
    }
    void submit({ kind: "review", payload });
  }
  if (!receipt)
    return (
      <>
        {error ? (
          <Notice error>
            {error}
            <Button variant="outline" onClick={() => setRevision((n) => n + 1)}>
              Reload receipt
            </Button>
          </Notice>
        ) : (
          <p role="status">Loading receipt…</p>
        )}
      </>
    );
  function update<K extends keyof Extraction>(key: K, value: Extraction[K]) {
    onDirty(true);
    setData((old) => (old ? { ...old, [key]: value } : old));
  }
  function line(
    index: number,
    key: keyof LineItem,
    value: string | number | null,
  ) {
    onDirty(true);
    setData((old) =>
      old
        ? {
            ...old,
            line_items: old.line_items.map((item, i) =>
              i === index ? { ...item, [key]: value } : item,
            ),
          }
        : old,
    );
  }
  const reasons = [
    ...new Set([
      ...(receipt.extracted_data?.review_reasons || []),
      ...(receipt.classification?.review_reasons || []),
    ]),
  ];
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="muted break-all font-mono">{id}</p>
        <Status
          value={
            (receipt.amendment ? "AMENDED" : null) ||
            receipt.review?.decision ||
            receipt.classification?.workflow_decision ||
            receipt.processing_status
          }
        />
      </div>
      {error && <Notice error>{error}</Notice>}
      {pending && !busy && (
        <Notice>
          The response was uncertain. Retry sends the exact same request safely,
          or reload to check what was saved.
          <div className="mt-2 flex flex-wrap gap-2">
            <Button onClick={() => void submit(pending)}>
              Retry same change
            </Button>
            <Button variant="outline" onClick={() => setRevision((n) => n + 1)}>
              Reload saved record
            </Button>
          </div>
        </Notice>
      )}
      {receipt.review && (
        <Notice>
          {receipt.review.decision === "APPROVED" ? "Approved" : "Rejected"} by{" "}
          {receipt.review.reviewer} on{" "}
          {new Date(receipt.review.reviewed_at).toLocaleString()}. The decision
          and original extraction remain in the audit record; approved data can
          be amended below.
        </Notice>
      )}
      {receipt.amendment && (
        <Notice>
          Effective data amended by {receipt.amendment.reviewer} on{" "}
          {new Date(receipt.amendment.amended_at).toLocaleString()}. Version{" "}
          {receipt.record_version}; every earlier version remains in the audit.
        </Notice>
      )}
      {receipt.error && <Notice error>{receipt.error}</Notice>}
      {!!receipt.duplicate_candidates?.length && (
        <Notice>
          Possible duplicate detected. Compare this receipt with{" "}
          {receipt.duplicate_candidates
            .map((candidate) => candidate.slice(0, 8))
            .join(", ")}
          {" "}before accepting it.
        </Notice>
      )}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section
          className="panel min-w-0 p-5 lg:sticky lg:top-5"
          aria-labelledby="evidence-title"
        >
          <div className="mb-4 flex items-center justify-between gap-2">
            <h2 id="evidence-title" className="text-lg font-semibold">
              Original receipt
            </h2>
            {image && (
              <a
                href={image}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium text-primary underline"
              >
                Open full size
              </a>
            )}
          </div>
          {imageError ? (
            <Notice error>{imageError}</Notice>
          ) : image && receipt.content_type === "application/pdf" ? (
            <div className="h-[70vh] overflow-hidden rounded-lg bg-muted p-3">
              <iframe
                src={image}
                title={`Original PDF receipt from ${receipt.extracted_data?.vendor || "uploaded vendor"}`}
                className="h-full w-full rounded bg-white"
                onError={() => {
                  setImageError("The PDF could not be displayed. Use Open full size.");
                }}
              />
            </div>
          ) : image ? (
            <div className="max-h-[70vh] overflow-auto rounded-lg bg-muted p-3">
              <img
                src={image}
                loading="lazy"
                alt={`Original receipt from ${receipt.extracted_data?.vendor || "uploaded vendor"}`}
                className="mx-auto h-auto max-w-full"
                onError={() => {
                  setImageError("The image could not be displayed.");
                  setImage("");
                }}
              />
            </div>
          ) : (
            <p role="status" className="muted">
              Loading original receipt…
            </p>
          )}
          <details className="mt-4">
            <summary className="text-sm font-medium">
              OCR text · {receipt.ocr_engine || "Unavailable"}
            </summary>
            <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 text-xs">
              {receipt.ocr_text || "No OCR text saved."}
            </pre>
          </details>
        </section>
        <div className="min-w-0 space-y-5">
          <section className="panel p-5">
            <h2 className="text-lg font-semibold">Decision context</h2>
            <p className="muted mt-3">Business purpose</p>
            <p className="mt-1 text-sm">
              {receipt.business_purpose ||
                "No purpose supplied. Confirm the business use with the submitter."}
            </p>
            {receipt.classification && (
              <>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">
                    {receipt.classification.category}
                  </Badge>
                  <span className="muted">
                    {Math.round(receipt.classification.confidence * 100)}% ·{" "}
                    {receipt.classification.source.replaceAll("_", " ")}
                  </span>
                </div>
                <p className="mt-3 text-sm">{receipt.classification.reason}</p>
              </>
            )}
            {reasons.length > 0 && (
              <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
                <p className="font-medium">Reasons to check</p>
                <ul className="mt-2 list-disc space-y-1 pl-5">
                  {reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            )}
          </section>
          {data && (
            <form
              ref={form}
              onSubmit={(e) => e.preventDefault()}
              className="panel space-y-6 p-5"
            >
              <div>
                <h2 className="text-lg font-semibold">
                  {amendable ? "Effective receipt data" : "Receipt data"}
                </h2>
                <p className="muted mt-1">
                  {editable
                    ? `Correct fields against the image. Blank values stay null. * Required for ${amendable ? "an amendment" : "approval"}.`
                    : "Read only. The original automated record is preserved."}
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {(
                  [
                    "vendor",
                    "legal_entity",
                    "company_registration_number",
                    "branch",
                    "receipt_number",
                    "date",
                    "payment_method",
                  ] as const
                ).map((key) => (
                  <Field
                    key={key}
                    name={
                      key === "date"
                        ? "Receipt date"
                        : key
                            .replaceAll("_", " ")
                            .replace(/^./, (c) => c.toUpperCase())
                    }
                    value={data[key]}
                    required={key === "vendor" || key === "date"}
                    disabled={locked}
                    set={(v) => update(key, v as string | null)}
                  />
                ))}
                <div>
                  <label id="currency-label" className="field-label">
                    Currency *
                  </label>
                  <Select
                    value={data.currency || ""}
                    disabled={locked}
                    onValueChange={(v) => update("currency", v)}
                  >
                    <SelectTrigger aria-labelledby="currency-label">
                      <SelectValue placeholder="Choose currency" />
                    </SelectTrigger>
                    <SelectContent>
                      {[
                        ...new Set([
                          "SGD",
                          "MYR",
                          "USD",
                          "EUR",
                          "GBP",
                          "AUD",
                          ...(data.currency ? [data.currency] : []),
                        ]),
                      ].map((c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-4">
                <h3 className="font-semibold">Line items</h3>
                {data.line_items.map((item, index) => (
                  <fieldset
                    key={index}
                    className="rounded-lg border p-4"
                    disabled={locked}
                  >
                    <legend className="px-1 text-sm font-medium">
                      Item {index + 1}
                    </legend>
                    <div className="grid gap-3 sm:grid-cols-2">
                      {(
                        [
                          "description",
                          "quantity",
                          "unit_price",
                          "discount_percent",
                          "discount_amount",
                          "line_total",
                        ] as const
                      ).map((key) => (
                        <Field
                          key={key}
                          name={`Item ${index + 1} ${key.replaceAll("_", " ")}`}
                          value={item[key]}
                          numeric={key !== "description"}
                          step={key === "quantity" ? "0.001" : "0.01"}
                          disabled={locked}
                          set={(v) => line(index, key, v)}
                        />
                      ))}
                    </div>
                    {editable && (
                      <Button
                        variant="ghost"
                        type="button"
                        className="mt-2 text-destructive"
                        disabled={locked}
                        onClick={() =>
                          update(
                            "line_items",
                            data.line_items.filter((_, i) => index !== i),
                          )
                        }
                      >
                        <Trash2 />
                        Remove item {index + 1}
                      </Button>
                    )}
                  </fieldset>
                ))}
                {editable && (
                  <Button
                    variant="outline"
                    type="button"
                    disabled={locked || data.line_items.length >= 200}
                    onClick={() =>
                      update("line_items", [
                        ...data.line_items,
                        { ...blankLine },
                      ])
                    }
                  >
                    <Plus />
                    Add line item
                  </Button>
                )}
                <p className="muted">
                  Discount fields are optional. Keep null when absent; use 0
                  only when zero is printed. Receipt totals may include tax or
                  rounding.
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {(
                  [
                    "subtotal",
                    "tax_amount",
                    "total_before_rounding",
                    "rounding_adjustment",
                    "total_amount",
                    "cash_tendered",
                    "change_amount",
                  ] as const
                ).map((key) => (
                  <Field
                    key={key}
                    name={key
                      .replaceAll("_", " ")
                      .replace(/^./, (c) => c.toUpperCase())}
                    value={data[key]}
                    numeric
                    disabled={locked}
                    required={key === "total_amount"}
                    set={(v) => update(key, v as number | null)}
                  />
                ))}
              </div>
            </form>
          )}
          {editable && (
            <section
              className="panel space-y-4 p-5"
              aria-labelledby="review-title"
            >
              <h2 id="review-title" className="text-lg font-semibold">
                Your review
              </h2>
              <div>
                <label id="category-label" className="field-label">
                  Final category {amendable ? "(amendment)" : "(approval)"}
                </label>
                <Select
                  value={category}
                  disabled={locked}
                  onValueChange={(value) => {
                    setCategory(value);
                    onDirty(true);
                  }}
                >
                  <SelectTrigger aria-labelledby="category-label">
                    <SelectValue placeholder="Choose category" />
                  </SelectTrigger>
                  <SelectContent>
                    {categories.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Field
                name="Reviewer name"
                value={reviewer}
                disabled={locked}
                set={(v) => {
                  setReviewer(String(v || ""));
                  onDirty(true);
                }}
              />
              <div>
                <label htmlFor="review-note" className="field-label">
                  {amendable ? "Amendment reason" : "Decision reason"}
                </label>
                <Textarea
                  id="review-note"
                  value={note}
                  disabled={locked}
                  maxLength={2000}
                  onChange={(e) => {
                    setNote(e.target.value);
                    onDirty(true);
                  }}
                  placeholder={
                    amendable
                      ? "Explain exactly what changed and why."
                      : "Explain the business use, correction, or reason for rejection."
                  }
                />
              </div>
              <details>
                <summary className="text-sm font-medium">
                  Override unresolved extraction issues (optional)
                </summary>
                <p className="muted mt-2">
                  Correct the data first. If an issue remains, explain the
                  evidence supporting approval. This explanation is saved in the
                  audit record.
                </p>
                <label htmlFor="override" className="field-label mt-3">
                  Override explanation (at least 10 characters)
                </label>
                <Textarea
                  id="override"
                  minLength={10}
                  maxLength={2000}
                  value={override}
                  disabled={locked}
                  onChange={(e) => {
                    setOverride(e.target.value);
                    onDirty(true);
                  }}
                />
              </details>
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 size-4 accent-primary"
                  checked={evidence}
                  disabled={locked || !image || !!imageError}
                  onChange={(e) => {
                    setEvidence(e.target.checked);
                    onDirty(true);
                  }}
                />
                I checked the original receipt, amounts, and business purpose.
                My decision is supported by this evidence.
              </label>
              <p className="muted">
                {amendable
                  ? "Save amendment creates a new effective version. Original OCR, AI output, review and earlier amendments remain unchanged."
                  : "Approve accepts the expense with your corrections. Reject excludes the expense; it keeps the receipt and audit record."}
              </p>
              <div className="flex flex-wrap gap-3">
                <Button
                  disabled={
                    locked || !data || !category || !image || !!imageError
                  }
                  onClick={() => prepare(amendable ? "AMENDMENT" : "APPROVED")}
                >
                  <FileCheck2 />
                  {amendable ? "Save amendment" : "Approve receipt"}
                </Button>
                {reviewable && (
                  <Button
                    variant="destructive"
                    disabled={locked || !image || !!imageError}
                    onClick={() => prepare("REJECTED")}
                  >
                    Reject receipt
                  </Button>
                )}
                {error && !pending && (
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => setRevision((n) => n + 1)}
                  >
                    Reload saved record
                  </Button>
                )}
              </div>
              {busy && (
                <p role="status" className="muted">
                  Saving {amendable ? "amendment" : "decision"}…
                </p>
              )}
            </section>
          )}
        </div>
      </div>
      <section className="panel p-5" aria-labelledby="audit-title">
        <h2 id="audit-title" className="text-lg font-semibold">
          Review audit
        </h2>
        {audit.length ? (
          audit.map((event) => (
            <div key={event.request_id} className="mt-4 rounded-lg border p-4">
              <div className="flex flex-wrap gap-3">
                <Status value={event.decision} />
                <span className="text-sm font-medium">{event.reviewer}</span>
                <span className="muted">
                  {new Date(event.reviewed_at).toLocaleString()} ·{" "}
                  {event.identity_source.replaceAll("_", " ")}
                </span>
              </div>
              <p className="mt-3 text-sm">{event.note}</p>
              {event.override_reason && (
                <p className="mt-2 text-sm">
                  Override: {event.override_reason}
                </p>
              )}
              <details className="mt-3">
                <summary className="text-sm font-medium">
                  Original and final audit data
                </summary>
                <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 text-xs">
                  {JSON.stringify(event, null, 2)}
                </pre>
              </details>
            </div>
          ))
        ) : (
          <p className="muted mt-3">No human review has been recorded.</p>
        )}
        {amendments.map((event) => (
          <div key={event.request_id} className="mt-4 rounded-lg border p-4">
            <div className="flex flex-wrap gap-3">
              <Status value="AMENDED" />
              <span className="text-sm font-medium">{event.reviewer}</span>
              <span className="muted">
                {new Date(event.amended_at).toLocaleString()} · version{" "}
                {event.record_version}
              </span>
            </div>
            <p className="mt-3 text-sm">{event.reason}</p>
          </div>
        ))}
      </section>
      <Dialog
        open={!!confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm === "AMENDMENT"
                ? "Save this amendment?"
                : confirm === "APPROVED"
                ? "Approve this expense?"
                : "Reject this expense?"}
            </DialogTitle>
            <DialogDescription>
              {confirm === "AMENDMENT"
                ? `Create version ${receipt.record_version + 1} as ${category}; earlier versions remain unchanged.`
                : confirm === "APPROVED"
                ? `Save the reviewed data as ${category}.`
                : "Exclude this expense from accepted expenses and retain the original record."}{" "}
              This change will be attributed to {reviewer}.
            </DialogDescription>
          </DialogHeader>
          <p className="rounded-lg bg-muted p-3 text-sm">{note}</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Keep reviewing
            </Button>
            <Button
              variant={confirm === "REJECTED" ? "destructive" : "default"}
              onClick={execute}
            >
              Confirm{" "}
              {confirm === "REJECTED"
                ? "rejection"
                : confirm === "AMENDMENT"
                  ? "amendment"
                  : "approval"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
