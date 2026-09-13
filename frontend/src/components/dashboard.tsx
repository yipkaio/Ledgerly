import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/feedback";
import { amount, message, request } from "@/lib/api";

type Currency = {
  currency: string;
  total_cents: number;
  receipt_count: number;
  categories: { category: string; total_cents: number }[];
  months: { month: string; total_cents: number }[];
};
type Summary = {
  total_receipts: number;
  counts: Record<string, number>;
  currencies: Currency[];
  accepted_missing_value: number;
  generated_at: string;
};

export function Dashboard({
  token,
  navigate,
}: {
  token: string;
  navigate: (view: "history" | "reviews" | "upload") => void;
}) {
  const [data, setData] = useState<Summary | null>(null),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0),
    [currency, setCurrency] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Clear the previous snapshot while loading a cancellable read.
    setData(null);
    setError("");
    request<Summary>("/dashboard", token, { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setData(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      });
    return () => controller.abort();
  }, [token, refresh]);
  const current =
    data?.currencies.find((item) => item.currency === currency) ||
    data?.currencies[0];
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="muted">
          A live snapshot of your saved receipts and review workload.
        </p>
        <Button variant="outline" onClick={() => setRefresh((n) => n + 1)}>
          <RefreshCw />
          Refresh dashboard
        </Button>
      </div>
      {error ? (
        <Notice error>{error}</Notice>
      ) : !data ? (
        <p role="status">Loading dashboard…</p>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {(
              [
                [
                  "All receipts",
                  data.total_receipts,
                  "Every saved processing record",
                  "history",
                ],
                [
                  "Pending reviews",
                  data.counts.REVIEW_QUEUE || 0,
                  "Waiting for a human decision",
                  "reviews",
                ],
                [
                  "Accepted receipts",
                  (data.counts.APPROVED || 0) + (data.counts.AUTO_FILED || 0),
                  `${data.counts.APPROVED || 0} approved · ${data.counts.AUTO_FILED || 0} auto filed`,
                  "history",
                ],
                [
                  "Processing issues",
                  (data.counts.FAILED || 0) + (data.counts.PROCESSING || 0),
                  `${data.counts.FAILED || 0} failed · ${data.counts.PROCESSING || 0} processing`,
                  "history",
                ],
              ] as const
            ).map(([label, count, help, view]) => (
              <button
                key={label}
                className="panel group p-5 text-left transition-shadow hover:shadow-md"
                onClick={() => navigate(view)}
              >
                <span className="field-label">{label}</span>
                <span className="block text-3xl font-semibold tabular-nums">
                  {count}
                </span>
                <span className="muted mt-2 block">{help}</span>
                <span className="mt-4 flex items-center gap-2 text-sm font-medium text-primary">
                  {view === "reviews" ? "Open review queue" : "Open history"}
                  <ArrowRight className="size-4" />
                </span>
              </button>
            ))}
          </div>
          <section
            className="panel p-5 sm:p-6"
            aria-labelledby="expense-overview"
          >
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h2 id="expense-overview" className="text-xl font-semibold">
                  Accepted expenses
                </h2>
                <p className="muted mt-1">
                  Approved and auto-filed receipts. Currencies are never
                  combined.
                </p>
              </div>
              {!!data.currencies.length && (
                <div>
                  <label htmlFor="dashboard-currency" className="field-label">
                    Currency
                  </label>
                  <select
                    id="dashboard-currency"
                    className="h-9 rounded-md border bg-white px-3"
                    value={current?.currency || ""}
                    onChange={(e) => setCurrency(e.target.value)}
                  >
                    {data.currencies.map((item) => (
                      <option key={item.currency}>{item.currency}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {!current ? (
              <div className="py-10">
                <p className="muted">
                  No accepted expenses with a known amount and currency yet.
                </p>
                <Button className="mt-4" onClick={() => navigate("upload")}>
                  Upload a receipt
                  <ArrowRight />
                </Button>
              </div>
            ) : (
              <>
                <p className="mt-6 text-3xl font-semibold tabular-nums">
                  {amount(current.total_cents / 100, current.currency)}
                </p>
                <p className="muted mt-1">
                  Across {current.receipt_count} accepted receipts · All time
                </p>
                <div className="mt-8 grid gap-8 xl:grid-cols-2">
                  <BarList
                    title="Expenses by category"
                    currency={current.currency}
                    items={current.categories.map((item) => ({
                      label: item.category,
                      cents: item.total_cents,
                    }))}
                  />
                  <BarList
                    title="Expense trend by receipt month"
                    currency={current.currency}
                    items={current.months.map((item) => ({
                      label: item.month,
                      cents: item.total_cents,
                    }))}
                  />
                </div>
                <p className="muted mt-6">
                  Trend shows the latest 12 months containing accepted receipts.
                  Months without entries are omitted. Rejected receipts (
                  {data.counts.REJECTED || 0}) are excluded from totals.
                </p>
              </>
            )}
            {!!data.accepted_missing_value && (
              <p className="muted mt-4">
                {data.accepted_missing_value} accepted receipts have an unknown
                amount or currency and are excluded from expense totals.
              </p>
            )}
          </section>
          <p className="muted">
            Updated {new Date(data.generated_at).toLocaleString()} · Workflow
            figures; no payments or accounting postings are made.
          </p>
        </>
      )}
    </div>
  );
}

function BarList({
  title,
  currency,
  items,
}: {
  title: string;
  currency: string;
  items: { label: string; cents: number }[];
}) {
  const max = Math.max(1, ...items.map((item) => Math.abs(item.cents)));
  return (
    <section aria-label={title}>
      <h3 className="mb-4 font-semibold">{title}</h3>
      {!items.length ? (
        <p className="muted">No dated receipts available.</p>
      ) : (
        <ul className="space-y-4">
          {items.map((item) => (
            <li key={item.label}>
              <div className="mb-1.5 flex justify-between gap-3 text-sm">
                <span>{item.label}</span>
                <span className="shrink-0 font-medium tabular-nums">
                  {amount(item.cents / 100, currency)}
                </span>
              </div>
              <div
                aria-hidden="true"
                className="h-2 overflow-hidden rounded-full bg-muted"
              >
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${(Math.abs(item.cents) / max) * 100}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
