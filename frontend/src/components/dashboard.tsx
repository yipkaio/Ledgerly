import { useEffect, useState } from "react";
import { TrendChart } from "@/components/expense-trend";
import {
  dateRangeLabel,
  presetDateRange,
  type DateBounds,
  type DateRange,
  type DateRangePreset,
  type MonthTotal,
} from "@/lib/dashboard-periods";
import {
  ArrowRight,
  CalendarDays,
  CircleAlert,
  CircleCheckBig,
  Clock3,
  Landmark,
  ReceiptText,
  RefreshCw,
  TrendingUp,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/feedback";
import { amount, message, request } from "@/lib/api";

type Currency = {
  currency: string;
  total_cents: number;
  receipt_count: number;
  categories: { category: string; total_cents: number }[];
  months: MonthTotal[];
};
type Summary = {
  total_receipts: number;
  counts: Record<string, number>;
  currencies: Currency[];
  accepted_count: number;
  accepted_missing_value: number;
  accepted_date_bounds: DateBounds;
  date_range: { from: string | null; to: string | null };
  generated_at: string;
  default_currency: string | null;
  reporting: (Currency & { available: boolean; as_of: string | null; source: string | null; stale: boolean }) | null;
};
type View = "history" | "reviews" | "upload" | "monthly";

export function Dashboard({ token, navigate, showAcceptedReceipts }: {
  token: string; navigate: (view: View) => void; showAcceptedReceipts: (range: DateRange) => void;
}) {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [currency, setCurrency] = useState("consolidated");
  const [range, setRange] = useState<DateRange>({ from: "", to: "" });
  const [draftRange, setDraftRange] = useState<DateRange>({ from: "", to: "" });
  const [preset, setPreset] = useState<DateRangePreset>("all");
  const [rangeError, setRangeError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Track the cancellable dashboard request.
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    if (preset === "all") params.set("dated_only", "true");
    if (range.from) params.set("date_from", range.from);
    if (range.to) params.set("date_to", range.to);
    request<Summary>(`/dashboard?${params}`, token, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        if (preset === "all") setDraftRange(presetDateRange("all", result.accepted_date_bounds));
        setData(result);
      })
      .catch((caught) => { if (!controller.signal.aborted) setError(message(caught)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, refresh, range, preset]);

  async function saveCurrency(value: string) {
    setSaving(true); setError("");
    try {
      await request("/workspace/settings", token, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ default_currency: value }),
      });
      setCurrency("consolidated");
      setRefresh((n) => n + 1);
    } catch (caught) { setError(message(caught)); }
    finally { setSaving(false); }
  }

  const reporting = data?.reporting;
  const selectedCurrency = data?.currencies.some((item) => item.currency === currency) ? currency : "consolidated";
  const current = selectedCurrency === "consolidated" && data?.default_currency
    ? (reporting?.available ? reporting : undefined)
    : data?.currencies.find((item) => item.currency === selectedCurrency) || data?.currencies[0];
  const bounds = data?.accepted_date_bounds || { first: null, last: null };
  const effectiveRange = {
    from: range.from || bounds.first || "",
    to: range.to || bounds.last || "",
  };
  const label = dateRangeLabel(range, bounds, preset === "all");

  function choosePreset(nextPreset: Exclude<DateRangePreset, "custom">) {
    const next = presetDateRange(nextPreset, bounds);
    setPreset(nextPreset);
    setDraftRange(next);
    setRange(nextPreset === "all" ? { from: "", to: "" } : next);
    setRangeError("");
  }

  function applyCustomRange() {
    if (!draftRange.from || !draftRange.to) {
      setRangeError("Choose both a start and end date.");
      return;
    }
    if (draftRange.from > draftRange.to) {
      setRangeError("Start date must be on or before end date.");
      return;
    }
    setPreset("custom");
    setRange(draftRange);
    setRangeError("");
  }
  return <div className="space-y-6">
    <div className="panel p-4 sm:p-5">
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-48 text-sm font-medium">
          <span className="mb-1.5 block">Default reporting currency</span>
          <select className="h-10 w-full rounded-lg border bg-white px-3" aria-label="Default reporting currency"
            value={data?.default_currency || ""} disabled={saving || loading || !data}
            onChange={(event) => void saveCurrency(event.target.value)}>
            <option value="" disabled>Choose currency</option>
            {["SGD", "MYR", "USD", "EUR", "GBP", "AUD"].map((code) => <option key={code}>{code}</option>)}
          </select>
        </label>
        <div className="min-w-0 basis-full border-t pt-4 sm:basis-auto sm:flex-1 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-4">
          <div className="mb-1.5 flex items-center gap-2 text-sm font-medium">
            <CalendarDays className="size-4 text-primary" /> Date range
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label="Accepted expenses start date" type="date" className="h-10 rounded-lg border bg-white px-3 text-sm"
              value={draftRange.from}
              onChange={(event) => { setDraftRange((old) => ({ ...old, from: event.target.value })); setRangeError(""); }} />
            <span className="text-sm text-muted-foreground" aria-hidden="true">to</span>
            <input aria-label="Accepted expenses end date" type="date" className="h-10 rounded-lg border bg-white px-3 text-sm"
              value={draftRange.to}
              onChange={(event) => { setDraftRange((old) => ({ ...old, to: event.target.value })); setRangeError(""); }} />
            <Button variant="outline" disabled={loading || !data || !bounds.first} onClick={applyCustomRange}>Apply dates</Button>
          </div>
        </div>
        <Button variant="outline" disabled={saving || loading} onClick={() => setRefresh((n) => n + 1)}><RefreshCw className={loading ? "animate-spin" : ""} /> Refresh</Button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t pt-4" aria-label="Quick date ranges">
        <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Quick range</span>
        {([ ["month", "Latest month"], ["three_months", "Latest 3 months"], ["year", "Latest year" ] ] as const).map(([value, text]) =>
          <Button key={value} size="sm" disabled={loading || !bounds.last} variant={preset === value ? "default" : "ghost"} onClick={() => choosePreset(value)}>{text}</Button>)}
        <Button size="sm" variant={preset === "all" ? "default" : "outline"} onClick={() => choosePreset("all")} disabled={loading || !bounds.first}>
          All time · first to latest receipt
        </Button>
        <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">{loading ? "Updating dashboard…" : label}</span>
      </div>
      {data && !bounds.first && <p className="muted mt-3 text-xs">No accepted receipts have a receipt date yet. Check Receipt history for undated records.</p>}
    </div>
    {rangeError && <Notice variant="destructive">{rangeError}</Notice>}
    {error && <Notice variant="destructive">{error}</Notice>}
    {!data ? <DashboardSkeleton /> : <>
      <section className="dashboard-hero overflow-hidden rounded-2xl border p-6 text-white shadow-sm sm:p-8">
        <div className="relative z-10 flex flex-wrap items-start justify-between gap-5">
          <div>
            <p className="flex items-center gap-2 text-sm text-emerald-100"><TrendingUp className="size-4" />Accepted expenses · {label}</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">{data.accepted_count === 0 ? "No dated accepted spend" : current ? amount(current.total_cents / 100, current.currency) : data.default_currency ? "Conversion unavailable" : "No accepted spend"}</h2>
            <p className="mt-3 text-sm text-emerald-50">{current?.receipt_count ?? 0} valued receipts · Includes amendments</p>
            {data.accepted_missing_value > 0 && <p className="mt-2 text-xs text-emerald-100">
              {data.accepted_missing_value} accepted {data.accepted_missing_value === 1 ? "receipt is" : "receipts are"} missing an amount or currency and excluded from spend.
            </p>}
          </div>
          <label className="text-sm">Display
            <select aria-label="Spend display" className="ml-2 rounded-lg border bg-white p-2 text-foreground" value={selectedCurrency}
              onChange={(event) => setCurrency(event.target.value)}>
              <option value="consolidated">{data.default_currency ? `All currencies → ${data.default_currency}` : data.currencies.length ? `${data.currencies[0].currency} only · Choose a default to consolidate` : "Native currency"}</option>
              {data.currencies.map((item) => <option key={item.currency} value={item.currency}>{item.currency} only</option>)}
            </select>
          </label>
        </div>
        {selectedCurrency === "consolidated" && data.default_currency && <p className="relative z-10 mt-4 text-xs text-emerald-100">
          {reporting?.available ? `Converted using ${reporting.source} rates dated ${reporting.as_of}${reporting.stale ? " · Cached rates" : ""}. Management estimate; original amounts are unchanged.`
            : "Exchange rates are unavailable. Refresh to retry or select a native currency; no partial converted total is shown."}
        </p>}
      </section>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Workspace summary">
        <MetricCard label="Monthly close" value="Reconcile" help="Match bank debits and receipt evidence" icon={<Landmark />} tone="violet" action="Open monthly close" onClick={() => navigate("monthly")} />
        <MetricCard label="Pending reviews" value={data.counts.REVIEW_QUEUE || 0} help="Needs a human decision" icon={<Clock3 />} tone="amber" action="Open review queue" onClick={() => navigate("reviews")} />
        <MetricCard label="Accepted receipts" value={data.accepted_count} help={label} icon={<CircleCheckBig />} tone="green" action="View this date range" onClick={() => showAcceptedReceipts(effectiveRange)} disabled={loading || !data.accepted_count} />
        <MetricCard label="All receipts" value={data.total_receipts} help="Every saved processing record" icon={<ReceiptText />} tone="blue" action="Open receipt history" onClick={() => navigate("history")} />
      </section>
      {current && <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(20rem,0.85fr)]">
        <TrendChart currency={current.currency} items={current.months} range={effectiveRange} rangeLabel={label} />
        <CategoryBreakdown currency={current.currency} items={current.categories} rangeLabel={label} />
      </div>}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.6fr)]">
        <WorkflowStatus counts={data.counts} total={data.total_receipts} navigate={navigate} /><AttentionPanel data={data} navigate={navigate} />
      </div>
      <p className="text-xs text-muted-foreground">Updated {new Date(data.generated_at).toLocaleString()}</p>
    </>}
  </div>;
}

function MetricCard({
  label,
  value,
  help,
  icon,
  tone,
  action,
  onClick,
  disabled,
}: {
  label: string;
  value: number | string;
  help: string;
  icon: React.ReactNode;
  tone: "amber" | "green" | "blue" | "violet";
  action: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  const tones = {
    amber: "bg-amber-50 text-amber-800",
    green: "bg-emerald-50 text-emerald-800",
    blue: "bg-sky-50 text-sky-800",
    violet: "bg-violet-50 text-violet-800",
  };
  return (
    <button
      className="panel group p-5 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:translate-y-0 disabled:hover:shadow-none"
      onClick={onClick}
      disabled={disabled}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <span className="field-label text-muted-foreground">{label}</span>
          <span className="block text-3xl font-semibold tabular-nums">{value}</span>
        </div>
        <span className={`rounded-xl p-2.5 [&>svg]:size-5 ${tones[tone]}`}>{icon}</span>
      </div>
      <span className="muted mt-2 block">{help}</span>
      <span className="mt-4 flex items-center gap-2 text-sm font-medium text-primary">
        {action}
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </button>
  );
}

function CategoryBreakdown({
  currency,
  items,
  rangeLabel,
}: {
  currency: string;
  items: Currency["categories"];
  rangeLabel: string;
}) {
  const max = Math.max(1, ...items.map((item) => item.total_cents));
  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="category-title">
      <h2 id="category-title" className="text-lg font-semibold">Top categories</h2>
      <p className="muted mt-1">{rangeLabel} · {currency}</p>
      {!items.length ? (
        <p className="muted py-12 text-center">No category totals yet.</p>
      ) : (
        <ol className="mt-6 space-y-5">
          {items.slice(0, 6).map((item, index) => (
            <li key={item.category}>
              <div className="mb-2 flex items-start justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2 font-medium">
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-xs text-primary">
                    {index + 1}
                  </span>
                  <span className="truncate">{item.category}</span>
                </span>
                <span className="shrink-0 font-semibold tabular-nums">
                  {amount(item.total_cents / 100, currency)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${Math.max(3, (item.total_cents / max) * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function WorkflowStatus({
  counts,
  total,
  navigate,
}: {
  counts: Record<string, number>;
  total: number;
  navigate: (view: View) => void;
}) {
  const rows = [
    ["Accepted", (counts.APPROVED || 0) + (counts.AUTO_FILED || 0), "bg-emerald-500"],
    ["Pending", counts.REVIEW_QUEUE || 0, "bg-amber-500"],
    ["Rejected", counts.REJECTED || 0, "bg-red-500"],
    [
      "Processing / failed",
      (counts.PROCESSING || 0) + (counts.FAILED || 0),
      "bg-slate-400",
    ],
  ] as const;
  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="workflow-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="workflow-title" className="text-lg font-semibold">Workflow status</h2>
          <p className="muted mt-1">{total} saved receipts</p>
        </div>
        <Button variant="ghost" onClick={() => navigate("history")}>
          View history <ArrowRight />
        </Button>
      </div>
      <div className="mt-6 flex h-3 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        {rows.map(
          ([label, value, color]) =>
            value > 0 && (
              <span
                key={label}
                className={color}
                style={{ width: `${(value / Math.max(1, total)) * 100}%` }}
              />
            ),
        )}
      </div>
      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {rows.map(([label, value, color]) => (
          <li
            key={label}
            className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-sm"
          >
            <span className="flex items-center gap-2">
              <span className={`size-2.5 rounded-full ${color}`} />
              {label}
            </span>
            <span className="font-semibold tabular-nums">{value}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function AttentionPanel({
  data,
  navigate,
}: {
  data: Summary;
  navigate: (view: View) => void;
}) {
  const issues = (data.counts.FAILED || 0) + (data.counts.PROCESSING || 0);
  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="attention-title">
      <div className="flex items-center gap-3">
        <span className="rounded-xl bg-amber-50 p-2.5 text-amber-800">
          <CircleAlert className="size-5" />
        </span>
        <div>
          <h2 id="attention-title" className="font-semibold">Needs attention</h2>
        </div>
      </div>
      <dl className="mt-5 divide-y rounded-xl border px-4">
        <div className="flex justify-between gap-3 py-3">
          <dt>Pending review</dt>
          <dd className="font-semibold tabular-nums">{data.counts.REVIEW_QUEUE || 0}</dd>
        </div>
        <div className="flex justify-between gap-3 py-3">
          <dt>Processing issues</dt>
          <dd className="font-semibold tabular-nums">{issues}</dd>
        </div>
        <div className="flex justify-between gap-3 py-3">
          <dt>Accepted, missing value</dt>
          <dd className="font-semibold tabular-nums">{data.accepted_missing_value}</dd>
        </div>
      </dl>
      <Button className="mt-5 w-full" variant="outline" onClick={() => navigate("reviews")}>
        Open pending reviews <ArrowRight />
      </Button>
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div role="status" aria-label="Loading dashboard" className="space-y-5 animate-pulse">
      <div className="h-56 rounded-2xl bg-emerald-900/15" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((item) => (
          <div key={item} className="h-36 rounded-xl bg-muted" />
        ))}
      </div>
      <span className="sr-only">Loading dashboard…</span>
    </div>
  );
}
