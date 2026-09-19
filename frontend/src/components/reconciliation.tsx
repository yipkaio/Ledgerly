import { CheckCircle2, CircleHelp, TriangleAlert } from "lucide-react";
import type { Extraction } from "@/lib/api";
import { amount } from "@/lib/api";

import { reconciliation } from "@/lib/reconciliation";

export function Reconciliation({ data }: { data: Extraction }) {
  const result = reconciliation(data);
  const incomplete = result.status === "incomplete";
  const matched = result.status === "matched";
  const Icon = incomplete ? CircleHelp : matched ? CheckCircle2 : TriangleAlert;
  return (
    <section
      aria-label="Totals reconciliation"
      className={`rounded-xl border p-4 ${incomplete ? "border-slate-200 bg-slate-50" : matched ? "border-emerald-200 bg-emerald-50/60" : "border-amber-300 bg-amber-50"}`}
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h3 className="font-semibold">
            {incomplete
              ? "Reconciliation incomplete"
              : matched
                ? "Totals match within 0.02"
                : "Totals need attention"}
          </h3>
          <p className="mt-1 text-sm">
            Subtotal − Receipt discount + Tax + Rounding = Expected total
          </p>
          <p className="mt-2 break-words font-mono text-sm tabular-nums">
            {amount(data.subtotal, data.currency)} −{" "}
            {amount(data.discount_amount ?? 0, data.currency)} +{" "}
            {amount(data.tax_amount, data.currency)} + (
            {amount(data.rounding_adjustment ?? 0, data.currency)}) ={" "}
            {amount(result.expected, data.currency)}
          </p>
          {!incomplete && (
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2 text-sm">
              <div>
                <dt>Recorded total</dt>
                <dd className="font-semibold">
                  {amount(data.total_amount, data.currency)}
                </dd>
              </div>
              <div>
                <dt>Difference (recorded − expected)</dt>
                <dd className="font-semibold">
                  {amount(result.difference, data.currency)}
                </dd>
              </div>
            </dl>
          )}
          {result.beforeRoundingDifference != null &&
            Math.abs(result.beforeRoundingDifference) > 0.02 && (
              <p className="mt-2 text-sm">
                The recorded before-rounding amount also differs by{" "}
                {amount(result.beforeRoundingDifference, data.currency)}.
              </p>
            )}
          <p className="mt-3 text-xs text-muted-foreground">
            {incomplete
              ? "Enter verified subtotal, tax and total to check. Missing tax is unknown, not zero. "
              : "Arithmetic check only; confirm the receipt and business purpose. "}
            Absent discount and rounding contribute zero to this check; stored
            fields are unchanged. Line-item discounts are already reflected in
            subtotal.
          </p>
        </div>
      </div>
    </section>
  );
}
