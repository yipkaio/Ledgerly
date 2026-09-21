import { useEffect, useState } from "react";
import { TrendChart } from "@/components/expense-trend";
import { monthNames, periodLabel, periodTotals, type PeriodMode, type MonthTotal } from "@/lib/dashboard-periods";
import {
  ArrowRight,
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
  accepted_missing_value: number;
  generated_at: string;
  default_currency: string | null;
  reporting: (Currency & { available: boolean; as_of: string | null; source: string | null; stale: boolean }) | null;
};
type View = "history" | "reviews" | "upload" | "monthly";

export function Dashboard({ token, navigate, showAcceptedReceipts }: {
  token: string; navigate: (view: View) => void; showAcceptedReceipts: () => void;
}) {
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [saving, setSaving] = useState(false);
  const [currency, setCurrency] = useState("consolidated");
  const [mode, setMode] = useState<PeriodMode>("month");
  const [year, setYear] = useState("");
  const [part, setPart] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Reset the cancellable dashboard snapshot.
    setData(null);
    setError("");
    request<Summary>("/dashboard", token, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setData(result); })
      .catch((caught) => { if (!controller.signal.aborted) setError(message(caught)); });
    return () => controller.abort();
  }, [token, refresh]);

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
  const current = currency === "consolidated" && data?.default_currency
    ? (reporting?.available ? reporting : undefined)
    : data?.currencies.find((item) => item.currency === currency) || data?.currencies[0];
  const latest = current?.months.at(-1)?.month || new Date().toISOString().slice(0, 7);
  const years = Array.from(new Set((current?.months || []).map((item) => item.month.slice(0, 4)))).sort().reverse();
  const activeYear = year || latest.slice(0, 4);
  const activePart = part || (mode === "quarter" ? Math.ceil(Number(latest.slice(5)) / 3) : Number(latest.slice(5)));
  const total = periodTotals(current?.months || [], mode, activeYear, activePart);
  const label = periodLabel(mode, activeYear, activePart);
  return <div className="space-y-6">
    <div className="flex flex-wrap items-end justify-between gap-3">
      <label className="text-sm font-medium">Default reporting currency
        <select className="ml-3 h-10 rounded-lg border bg-white px-3" aria-label="Default reporting currency"
          value={data?.default_currency || ""} disabled={saving || !data}
          onChange={(event) => void saveCurrency(event.target.value)}>
          <option value="" disabled>Choose currency</option>
          {["SGD", "MYR", "USD", "EUR", "GBP", "AUD"].map((code) => <option key={code}>{code}</option>)}
        </select>
      </label>
      <Button variant="outline" disabled={saving} onClick={() => setRefresh((n) => n + 1)}><RefreshCw /> Refresh</Button>
    </div>
    {error && <Notice variant="destructive">{error}</Notice>}
    {!data ? <DashboardSkeleton /> : <>
      <section className="dashboard-hero overflow-hidden rounded-2xl border p-6 text-white shadow-sm sm:p-8">
        <div className="relative z-10 flex flex-wrap items-start justify-between gap-5">
          <div>
            <p className="flex items-center gap-2 text-sm text-emerald-100"><TrendingUp className="size-4" />Accepted expenses · {label}</p>
            <h2 className="mt-3 text-4xl font-semibold tracking-tight sm:text-5xl">{current ? amount(total.total_cents / 100, current.currency) : data.default_currency ? "Conversion unavailable" : "No accepted spend"}</h2>
            <p className="mt-3 text-sm text-emerald-50">{total.receipt_count} accepted receipts · Includes amendments</p>
          </div>
          <label className="text-sm">Display
            <select aria-label="Spend display" className="ml-2 rounded-lg border bg-white p-2 text-foreground" value={currency}
              onChange={(event) => setCurrency(event.target.value)}>
              <option value="consolidated">{data.default_currency ? `All currencies → ${data.default_currency}` : "Native currency"}</option>
              {data.currencies.map((item) => <option key={item.currency} value={item.currency}>{item.currency} only</option>)}
            </select>
          </label>
        </div>
        <div className="relative z-10 mt-6 flex flex-wrap gap-3 text-foreground">
          <label className="text-sm"><span className="mb-1 block text-emerald-100">Period</span>
            <select aria-label="Expense period" className="h-10 rounded-lg bg-white px-3" value={mode} onChange={(event) => { setMode(event.target.value as PeriodMode); setPart(0); }}>
              <option value="month">Month and year</option><option value="quarter">Quarter</option><option value="year">Full year</option>
            </select>
          </label>
          <label className="text-sm"><span className="mb-1 block text-emerald-100">Year</span>
            <select aria-label="Expense year" className="h-10 rounded-lg bg-white px-3" value={activeYear} onChange={(event) => setYear(event.target.value)}>
              {Array.from(new Set([...years, activeYear])).sort().reverse().map((value) => <option key={value}>{value}</option>)}
            </select>
          </label>
          {mode !== "year" && <label className="text-sm"><span className="mb-1 block text-emerald-100">{mode === "month" ? "Month" : "Quarter"}</span>
            <select aria-label="Expense month or quarter" className="h-10 rounded-lg bg-white px-3" value={activePart} onChange={(event) => setPart(Number(event.target.value))}>
              {(mode === "month" ? monthNames : ["Q1", "Q2", "Q3", "Q4"]).map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
            </select>
          </label>}
        </div>
        {currency === "consolidated" && data.default_currency && <p className="relative z-10 mt-4 text-xs text-emerald-100">
          {reporting?.available ? `Converted using ${reporting.source} rates dated ${reporting.as_of}${reporting.stale ? " · Cached rates" : ""}. Management estimate; original amounts are unchanged.`
            : "Exchange rates are unavailable. Refresh to retry or select a native currency; no partial converted total is shown."}
        </p>}
      </section>
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Workspace summary">
        <MetricCard label="Monthly close" value="Reconcile" help="Match bank debits and receipt evidence" icon={<Landmark />} tone="violet" action="Open monthly close" onClick={() => navigate("monthly")} />
        <MetricCard label="Pending reviews" value={data.counts.REVIEW_QUEUE || 0} help="Needs a human decision" icon={<Clock3 />} tone="amber" action="Open review queue" onClick={() => navigate("reviews")} />
        <MetricCard label="Accepted receipts" value={(data.counts.APPROVED || 0) + (data.counts.AUTO_FILED || 0)} help="Approved, auto-filed and amended" icon={<CircleCheckBig />} tone="green" action="View accepted receipts" onClick={showAcceptedReceipts} />
        <MetricCard label="All receipts" value={data.total_receipts} help="Every saved processing record" icon={<ReceiptText />} tone="blue" action="Open receipt history" onClick={() => navigate("history")} />
      </section>
      {current && <div className="grid gap-6 xl:grid-cols-[minmax(0,1.55fr)_minmax(20rem,0.85fr)]">
        <TrendChart currency={current.currency} items={current.months} />
        <CategoryBreakdown currency={current.currency} items={current.categories} />
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
}: {
  label: string;
  value: number | string;
  help: string;
  icon: React.ReactNode;
  tone: "amber" | "green" | "blue" | "violet";
  action: string;
  onClick: () => void;
}) {
  const tones = {
    amber: "bg-amber-50 text-amber-800",
    green: "bg-emerald-50 text-emerald-800",
    blue: "bg-sky-50 text-sky-800",
    violet: "bg-violet-50 text-violet-800",
  };
  return (
    <button
      className="panel group p-5 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-md"
      onClick={onClick}
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
}: {
  currency: string;
  items: Currency["categories"];
}) {
  const max = Math.max(1, ...items.map((item) => item.total_cents));
  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="category-title">
      <h2 id="category-title" className="text-lg font-semibold">Top categories</h2>
      <p className="muted mt-1">All accepted receipts in {currency}</p>
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
