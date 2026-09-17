import { Check, FilePenLine, ShieldCheck } from "lucide-react";
import { Status } from "@/components/feedback";
import type { Amendment, Extraction, Review } from "@/lib/api";

type Change = { field: string; before: string; after: string };

const labels: Record<string, string> = {
  vendor: "Vendor",
  legal_entity: "Legal entity",
  company_registration_number: "Registration number",
  branch: "Branch",
  receipt_number: "Receipt number",
  date: "Receipt date",
  currency: "Currency",
  subtotal: "Subtotal",
  discount_amount: "Receipt discount",
  tax_amount: "Tax",
  total_before_rounding: "Total before rounding",
  rounding_adjustment: "Rounding adjustment",
  total_amount: "Total amount",
  cash_tendered: "Cash tendered",
  change_amount: "Change",
  payment_method: "Payment method",
};

function shown(value: unknown) {
  if (value == null || value === "") return "Not set";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value);
}

function changes(before: Extraction | undefined, after: Extraction | null): Change[] {
  if (!before || !after) return [];
  const result: Change[] = [];
  for (const key of Object.keys(labels) as (keyof Extraction)[]) {
    const oldValue = before[key];
    const newValue = after[key];
    if (JSON.stringify(oldValue) !== JSON.stringify(newValue)) {
      result.push({ field: labels[key], before: shown(oldValue), after: shown(newValue) });
    }
  }
  const count = Math.max(before.line_items.length, after.line_items.length);
  for (let index = 0; index < count; index += 1) {
    const oldItem = before.line_items[index];
    const newItem = after.line_items[index];
    if (!oldItem || !newItem) {
      result.push({
        field: `Line item ${index + 1}`,
        before: oldItem?.description || "Not present",
        after: newItem?.description || "Removed",
      });
      continue;
    }
    const itemLabels: Record<keyof typeof oldItem, string> = {
      description: "description",
      quantity: "quantity",
      unit_price: "unit price",
      discount_percent: "discount percent",
      discount_amount: "discount amount",
      line_total: "line total",
    };
    for (const key of Object.keys(itemLabels) as (keyof typeof oldItem)[]) {
      if (oldItem[key] !== newItem[key]) {
        result.push({
          field: `Item ${index + 1} ${itemLabels[key]}`,
          before: shown(oldItem[key]),
          after: shown(newItem[key]),
        });
      }
    }
  }
  return result;
}

function ChangeList({ items }: { items: Change[] }) {
  if (!items.length) return <p className="muted mt-3">No receipt fields were changed.</p>;
  return (
    <div className="mt-4 overflow-hidden rounded-lg border">
      <div className="grid grid-cols-[minmax(7rem,0.8fr)_1fr_1fr] gap-3 bg-muted px-3 py-2 text-xs font-semibold text-muted-foreground uppercase">
        <span>Field</span><span>Before</span><span>After</span>
      </div>
      {items.map((item) => (
        <div key={`${item.field}-${item.before}-${item.after}`} className="grid grid-cols-[minmax(7rem,0.8fr)_1fr_1fr] gap-3 border-t px-3 py-2.5 text-sm">
          <span className="font-medium">{item.field}</span>
          <span className="break-words text-muted-foreground line-through decoration-red-300">{item.before}</span>
          <span className="break-words font-medium text-primary">{item.after}</span>
        </div>
      ))}
    </div>
  );
}

function Checks({ category, evidence }: { category?: string | null; evidence: boolean }) {
  return (
    <ul className="mt-4 grid gap-2 text-sm sm:grid-cols-2" aria-label="What was reviewed">
      <li className="flex items-center gap-2"><Check className="size-4 text-primary" /> Original evidence {evidence ? "confirmed" : "not confirmed"}</li>
      <li className="flex items-center gap-2"><Check className="size-4 text-primary" /> {category ? `Category: ${category}` : "No category accepted"}</li>
    </ul>
  );
}

export function AuditTimeline({
  reviews,
  amendments,
}: {
  reviews: Review[];
  amendments: Amendment[];
}) {
  const events = [
    ...reviews.map((event) => ({ kind: "review" as const, date: event.reviewed_at, event })),
    ...amendments.map((event) => ({ kind: "amendment" as const, date: event.amended_at, event })),
  ].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="audit-title">
      <div className="flex items-start gap-3">
        <div className="rounded-lg bg-primary/10 p-2 text-primary"><ShieldCheck className="size-5" /></div>
        <div>
          <h2 id="audit-title" className="text-lg font-semibold">Review audit</h2>
          <p className="muted mt-1">An append-only timeline of human decisions and corrections.</p>
        </div>
      </div>
      {!events.length ? (
        <p className="muted mt-5">No human review or amendment has been recorded.</p>
      ) : (
        <ol className="relative mt-6 space-y-5 border-l border-border pl-6">
          {events.map(({ kind, event }) => {
            const isReview = kind === "review";
            const before = isReview ? event.before?.extracted_data : event.before?.final_data;
            const after = event.final_data;
            const itemChanges = changes(before, after);
            const categoryBefore = isReview ? event.before?.classification.category : event.before?.category;
            if (after && event.category && categoryBefore !== event.category) {
              itemChanges.unshift({ field: "Category", before: shown(categoryBefore), after: event.category });
            }
            const title = isReview
              ? event.decision === "APPROVED" ? "Expense approved" : "Expense rejected"
              : `Receipt amended · Version ${event.record_version}`;
            const note = isReview ? event.note : event.reason;
            return (
              <li key={event.request_id} className="relative">
                <span className="absolute -left-[2.05rem] top-1 flex size-4 items-center justify-center rounded-full bg-white ring-4 ring-white">
                  <span className={`size-2.5 rounded-full ${isReview && event.decision === "REJECTED" ? "bg-red-500" : kind === "amendment" ? "bg-sky-500" : "bg-emerald-500"}`} />
                </span>
                <article className="rounded-xl border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Status value={isReview ? event.decision : "AMENDED"} />
                        <h3 className="font-semibold">{title}</h3>
                      </div>
                      <p className="muted mt-1">{event.reviewer} · {new Date(isReview ? event.reviewed_at : event.amended_at).toLocaleString()}</p>
                    </div>
                    {!isReview && <span className="flex items-center gap-1 text-xs font-medium text-sky-800"><FilePenLine className="size-3.5" />Version {event.before?.record_version ?? event.record_version - 1} → {event.record_version}</span>}
                  </div>
                  <p className={`mt-3 text-sm ${isReview && event.decision === "REJECTED" ? "font-medium text-red-800" : ""}`}>{note}</p>
                  <Checks category={event.category} evidence={event.evidence_confirmed} />
                  {isReview && event.decision === "REJECTED" ? (
                    <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-900">No corrected receipt data was accepted. The expense remains excluded while its original evidence is retained.</p>
                  ) : (
                    <ChangeList items={itemChanges} />
                  )}
                  {(event.override_reason || event.validation_issues.length > 0) && (
                    <div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-950">
                      {event.override_reason && <p><span className="font-medium">Override:</span> {event.override_reason}</p>}
                      {event.validation_issues.length > 0 && <p className="mt-1"><span className="font-medium">Validation notes:</span> {event.validation_issues.join("; ")}</p>}
                    </div>
                  )}
                  <details className="mt-4 text-xs text-muted-foreground">
                    <summary className="font-medium">Technical reference</summary>
                    <p className="mt-2 break-all font-mono">Request {event.request_id}</p>
                  </details>
                </article>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
