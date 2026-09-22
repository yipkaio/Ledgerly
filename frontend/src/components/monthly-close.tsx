import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  FileSpreadsheet,
  Landmark,
  Lightbulb,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Notice, Status } from "@/components/feedback";
import { FinanceCopilot } from "@/components/finance-copilot";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { amount, authenticationHeaders, message, request, requestDownload } from "@/lib/api";
import type { PaymentEvent } from "@/lib/api";
import { PaymentHistory } from "@/components/payment-history";
import { CopilotAgent } from "@/components/copilot-agent";

type ReviewState = { status: "not_reviewed" | "reviewed" | "outdated"; fingerprint: string; actor: string | null; note: string | null; reviewed_at: string | null };
type Period = { month: string; currency: string; statement_count: number; transaction_count: number; receipt_count: number; exception_count: number; bank_missing_count: number; receipt_unmatched_count: number; duplicate_count: number; review: ReviewState };
type Transaction = {
  transaction_id: string; posted_date: string; description: string; amount_cents: number;
  reference: string | null; receipt_id: string | null; receipt_vendor: string | null; status: string;
  statement_id: string;
  adjacent_month_candidate?: { month: string; receipt_id: string } | null;
};
type ReceiptRow = {
  receipt_id: string; receipt_date: string; vendor: string; category: string; amount_cents: number;
  status: string; transaction_id: string | null; duplicate_receipt: boolean;
  adjacent_month_candidate?: { month: string; statement_id: string } | null;
  payment_event: PaymentEvent | null; payment_events: PaymentEvent[];
};
type StatementRecord = {
  statement_id: string; account_label: string; original_filename: string; uploaded_at: string;
  row_count: number; skipped_rows: number; source_media_type?: string; extraction_method?: string;
  imported_by?: string;
};
type Reconciliation = {
  month: string; currency: string;
  statements: StatementRecord[];
  removed_statements: StatementRecord[];
  transactions: Transaction[]; receipts: ReceiptRow[];
  totals: { bank_debits_cents: number; receipt_spend_cents: number; matched_cents: number; difference_cents: number; exception_count: number };
  categories: { category: string; total_cents: number }[];
  vendors: { vendor: string; total_cents: number }[];
  suggestions: { title: string; detail: string }[];
  generated_at: string;
  review: ReviewState;
};

const currentMonth = new Date().toISOString().slice(0, 7);
function monthLabel(value: string) {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value)
    ? new Date(`${value}-01T12:00:00Z`).toLocaleDateString("en-SG", { month: "long", year: "numeric", timeZone: "UTC" })
    : "Choose a month";
}

export type MonthlyCloseLocation = {
  view: "overview" | "detail";
  month: string;
  currency: string;
  exceptionsOnly: boolean;
  statementFilter: string;
};

export function MonthlyClose({ token, openReceipt, initialLocation }: {
  token: string;
  openReceipt: (id: string, location: MonthlyCloseLocation) => void;
  initialLocation?: MonthlyCloseLocation | null;
}) {
  const [periods, setPeriods] = useState<Period[]>([]);
  const [view, setView] = useState<"overview" | "detail">(initialLocation?.view ?? "overview");
  const [periodsBusy, setPeriodsBusy] = useState(true);
  const [year, setYear] = useState("all");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const [month, setMonth] = useState(initialLocation?.month ?? currentMonth);
  const [currency, setCurrency] = useState(initialLocation?.currency ?? "SGD");
  const [data, setData] = useState<Reconciliation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [exportBusy, setExportBusy] = useState(false);
  const [sourceStatement, setSourceStatement] = useState<StatementRecord | null>(null);
  const [lifecycleTarget, setLifecycleTarget] = useState<{ statement: StatementRecord; restore: boolean } | null>(null);
  const [success, setSuccess] = useState("");
  const [exceptionsOnly, setExceptionsOnly] = useState(initialLocation?.exceptionsOnly ?? false);
  const [statementFilter, setStatementFilter] = useState(initialLocation?.statementFilter ?? "");
  const [reviewOpen, setReviewOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  function openReceiptFromMonth(id: string) {
    openReceipt(id, { view, month, currency, exceptionsOnly, statementFilter });
  }

  useEffect(() => {
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Asynchronous request state.
    setPeriodsBusy(true);
    request<{ items: Period[] }>("/bank-statements/periods", token, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setPeriods(result.items);
      })
      .catch((e) => !controller.signal.aborted && setError(message(e)))
      .finally(() => !controller.signal.aborted && setPeriodsBusy(false));
    return () => controller.abort();
  }, [token, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    if (view !== "detail") return () => controller.abort();
    // oxlint-disable-next-line react/set-state-in-effect -- Reset status for this cancellable API read.
    setBusy(true); setData(null); setError("");
    request<Reconciliation>(`/reconciliation?month=${month}&currency=${currency}`, token, { signal: controller.signal })
      .then((result) => !controller.signal.aborted && setData(result))
      .catch((e) => !controller.signal.aborted && setError(message(e)))
      .finally(() => !controller.signal.aborted && setBusy(false));
    return () => controller.abort();
  }, [token, month, currency, refresh, view]);

  const periodValue = `${month}|${currency}`;
  const matchedPercent = data?.totals.receipt_spend_cents
    ? Math.min(100, Math.round((data.totals.matched_cents / data.totals.receipt_spend_cents) * 100)) : 0;
  const missingDebitCount = data?.transactions.filter((item) => item.status === "MISSING_RECEIPT").length ?? 0;
  const unmatchedReceiptCount = data?.receipts.filter((item) => item.status !== "PAID").length ?? 0;
  const duplicateCount = (data?.transactions.filter((item) => item.status === "DUPLICATE_TRANSACTION").length ?? 0) +
    (data?.receipts.filter((item) => item.duplicate_receipt).length ?? 0);
  const years = [...new Set(periods.map((item) => item.month.slice(0, 4)))].sort().reverse();
  const attentionCount = periods.filter((item) => item.statement_count === 0 || item.exception_count > 0 || item.review.status === "outdated").length;
  const isAttention = (item: Period) => item.statement_count === 0 || item.exception_count > 0 || item.review.status === "outdated";
  const visiblePeriods = periods.filter((item) => (year === "all" || item.month.startsWith(year)) &&
    (!attentionOnly || isAttention(item))).sort((a, b) => Number(isAttention(b)) - Number(isAttention(a)) || b.month.localeCompare(a.month) || a.currency.localeCompare(b.currency));
  const now = new Date();
  const todayIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  function openPeriod(nextMonth: string, nextCurrency: string) {
    setSourceStatement(null); setStatementFilter(""); setSuccess("");
    setMonth(nextMonth); setCurrency(nextCurrency); setView("detail");
  }

  async function exportMonth() {
    setExportBusy(true); setError("");
    try {
      const result = await requestDownload("/reconciliation/export", token, { month, currency });
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a"); link.href = url; link.download = result.filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(message(e)); } finally { setExportBusy(false); }
  }
  async function downloadSource(statementId: string, filename: string) {
    setError("");
    try {
      const response = await fetch(`/bank-statements/${statementId}/source`, {
        headers: authenticationHeaders(token), cache: "no-store", signal: AbortSignal.timeout(30000),
      });
      if (!response.ok) throw new Error("The source statement could not be downloaded.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(message(e)); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex rounded-lg border bg-white p-1" role="group" aria-label="Monthly close view">
          <Button size="sm" variant={view === "overview" ? "default" : "ghost"} onClick={() => setView("overview")}>Overview</Button>
          <Button size="sm" variant={view === "detail" ? "default" : "ghost"} onClick={() => setView("detail")}>Month detail</Button>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatementUpload token={token} completed={(nextMonth, nextCurrency) => { openPeriod(nextMonth, nextCurrency); setRefresh((value) => value + 1); }} />
          {view === "detail" && <Button variant="outline" disabled={!data || busy || exportBusy} onClick={() => void exportMonth()}>
            {exportBusy ? <LoaderCircle className="animate-spin" /> : <Download />} Export month
          </Button>}
          <Button variant="ghost" onClick={() => setRefresh((value) => value + 1)}><RefreshCw /> Refresh</Button>
        </div>
      </div>

      {view === "overview" && <>
        <section className="rounded-2xl border border-emerald-900/15 bg-gradient-to-br from-emerald-950 to-emerald-800 p-5 text-white shadow-sm sm:p-7" aria-labelledby="overview-title">
          <div className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-sm font-medium text-emerald-100">Reconciliation workspace</p><h2 id="overview-title" className="mt-1 text-2xl font-semibold">Every month in view</h2><p className="mt-2 max-w-2xl text-sm text-emerald-50">Find months with missing statements, unmatched evidence or a review that needs repeating. Open a month to inspect the original records.</p></div><CalendarDays className="size-9 text-emerald-200" aria-hidden="true" /></div>
          <div className="mt-5 flex flex-wrap gap-3 text-sm"><span className="rounded-full bg-white/15 px-3 py-1.5">{periods.length} recorded periods</span><span className="rounded-full bg-white/15 px-3 py-1.5">{attentionCount} need attention</span><span className="rounded-full bg-white/15 px-3 py-1.5">{periods.filter((item) => item.review.status === "not_reviewed").length} not reviewed</span></div>
        </section>
        <section className="panel overflow-hidden" aria-label="Months to review">
          <div className="flex flex-wrap items-end justify-between gap-4 border-b p-5">
            <div><h2 className="text-lg font-semibold">Review periods</h2><p className="muted mt-1">Periods come from accepted receipts and imported statements. Amounts stay in their original currencies.</p></div>
            <div className="flex flex-wrap items-center gap-3"><label className="text-sm">Year <select className="ml-2 rounded-lg border bg-white px-3 py-2" value={year} onChange={(e) => setYear(e.target.value)}><option value="all">All years</option>{years.map((value) => <option key={value}>{value}</option>)}</select></label><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={attentionOnly} onChange={(e) => setAttentionOnly(e.target.checked)} />Needs attention only</label></div>
          </div>
          {error && <div className="p-4"><Notice variant="destructive">{error}</Notice></div>}
          {periodsBusy ? <p role="status" className="muted p-6">Loading periods…</p> : !periods.length ? <p className="muted p-6">No accepted receipts or statements yet. Upload a statement or add a receipt to begin.</p> : !visiblePeriods.length ? <p className="muted p-6">No periods match these filters. Try All years or show all periods.</p> : <div className="divide-y">{visiblePeriods.map((item) => {
            const needsStatement = item.statement_count === 0;
            const needsAttention = needsStatement || item.exception_count > 0 || item.review.status === "outdated";
            return <article key={`${item.month}-${item.currency}`} className="flex flex-wrap items-center justify-between gap-4 p-5 transition-colors hover:bg-emerald-50/40"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="font-semibold">{new Date(`${item.month}-01T12:00:00Z`).toLocaleDateString("en-SG", { month: "long", year: "numeric", timeZone: "UTC" })}</h3><span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium">{item.currency}</span><span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${needsAttention ? "bg-amber-100 text-amber-900" : item.review.status === "reviewed" ? "bg-emerald-100 text-emerald-900" : "bg-slate-100 text-slate-700"}`}>{needsStatement ? "No statement" : item.review.status === "outdated" ? "Review outdated" : item.exception_count ? `${item.exception_count} exceptions` : item.review.status === "reviewed" ? "Reviewed" : "Not reviewed"}</span></div><p className="muted mt-2">{item.statement_count} statements · {item.transaction_count} bank debits · {item.receipt_count} accepted receipts</p><p className="mt-1 text-xs text-muted-foreground">{item.bank_missing_count} debits missing receipts · {item.receipt_unmatched_count} receipts without bank match · {item.duplicate_count} possible duplicates{item.review.status === "reviewed" && item.exception_count ? " · reviewed with exceptions" : ""}</p></div><Button variant={needsAttention ? "default" : "outline"} onClick={() => openPeriod(item.month, item.currency)}>Open month <ArrowRight /></Button></article>;
          })}</div>}
        </section>
        <p className="text-xs text-muted-foreground">Months without either a statement or an accepted receipt have no recorded activity and are not listed. A reviewed month can still contain documented exceptions.</p>
      </>}

      {view === "detail" && <>
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-800 p-5 text-white shadow-sm sm:p-7" aria-labelledby="month-detail-title">
        <div className="relative flex flex-wrap items-start justify-between gap-5">
          <div>
            <p className="text-xs font-semibold tracking-[0.14em] text-emerald-200 uppercase">Monthly reconciliation · {currency}</p>
            <h2 id="month-detail-title" className="mt-2 text-2xl font-semibold sm:text-3xl">{monthLabel(month)}</h2>
            <p className="mt-2 max-w-xl text-sm text-emerald-50/90">Compare bank activity with accepted receipts, then record your review of the source evidence.</p>
          </div>
          <Button variant="outline" size="sm" className="border-white/40 bg-white/10 text-white hover:bg-white/20 hover:text-white" onClick={() => setView("overview")}>All months <ArrowRight className="rotate-180" /></Button>
        </div>
        <div className="relative mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-white/20 pt-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className={`rounded-full px-3 py-1 font-medium ${data?.review.status === "outdated" ? "bg-amber-100 text-amber-950" : data?.review.status === "reviewed" ? "bg-emerald-100 text-emerald-950" : "bg-white/15 text-white"}`}>
              {!data ? "Loading review…" : data.review.status === "outdated" ? "Review outdated" : data.review.status === "reviewed" ? "Reviewed" : "Not reviewed"}
            </span>
            {data && <span className="text-emerald-100">{data.statements.length} statements · {data.transactions.length} bank debits · {data.receipts.length} receipts</span>}
          </div>
          <Button variant="secondary" size="sm" disabled={!data?.statements.length} onClick={() => setReviewOpen(true)}>{!data || data.review.status === "not_reviewed" ? "Mark reviewed" : "Review again"}</Button>
        </div>
        {data && <p className="relative mt-3 text-sm text-emerald-50/90">
          {!data.statements.length ? "Add a statement before recording a review." : data.review.status === "outdated" ? "The recorded evidence changed since the last review. Recheck this month before reviewing again." : data.review.status === "reviewed" ? `Reviewed by ${data.review.actor} · ${new Date(data.review.reviewed_at!).toLocaleString("en-SG")}${data.totals.exception_count ? " · exceptions remain visible" : ""}` : "Review the retained statement and receipts before marking this month reviewed."}
          {data.review.note && <span className="mt-1 block text-emerald-100">Review note: {data.review.note}</span>}
        </p>}
      </section>

      <section className="panel p-4 sm:p-5" aria-label="Reconciliation period">
        <div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-800"><CalendarDays className="size-5" /></span><div><h2 className="font-semibold">Period in view</h2><p className="muted">Switch to another recorded period or inspect a month manually.</p></div></div>
        <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <div>
            <label htmlFor="close-period" className="field-label">Recorded month and currency</label>
            <select id="close-period" className="h-10 w-full rounded-md border bg-white px-3" value={periodValue}
              onChange={(event) => { const [nextMonth, nextCurrency] = event.target.value.split("|"); setSourceStatement(null); setMonth(nextMonth); setCurrency(nextCurrency); }}>
              {!periods.some((item) => `${item.month}|${item.currency}` === periodValue) && <option value={periodValue}>{month} · {currency} · no statement</option>}
              {periods.map((item) => <option key={`${item.month}-${item.currency}`} value={`${item.month}|${item.currency}`}>{item.month} · {item.currency} · {item.statement_count ? `${item.transaction_count} debits` : "no statement"}</option>)}
            </select>
          </div>
          {data && !busy && <a href="#close-evidence" className="inline-flex h-10 items-center justify-center gap-2 rounded-lg border px-4 text-sm font-medium text-primary hover:bg-emerald-50">Jump to evidence <ArrowRight className="size-4" /></a>}
        </div>
        <details className="group mt-4 border-t pt-3"><summary className="w-fit text-sm font-medium text-primary hover:underline">Check a different month or currency</summary><div className="mt-3 flex flex-wrap gap-3"><div><label htmlFor="manual-month" className="field-label">Month</label><Input id="manual-month" type="month" value={month} onChange={(event) => { setSourceStatement(null); setMonth(event.target.value); }} /></div><div><label htmlFor="manual-currency" className="field-label">Currency</label><select id="manual-currency" className="h-10 rounded-lg border bg-white px-3" value={currency} onChange={(event) => { setSourceStatement(null); setCurrency(event.target.value); }}>{["SGD", "MYR", "USD", "EUR", "GBP", "AUD"].map((code) => <option key={code}>{code}</option>)}</select></div></div></details>
      </section>

      {success && <Notice>{success}</Notice>}
      {error && <Notice variant="destructive">{error}</Notice>}
      {busy ? <MonthlySkeleton /> : data && <>
        {!data.statements.length && <Notice variant="warning">No {currency} statement is loaded for {month}. Accepted receipts are still shown so you can see what needs a bank match.</Notice>}
        <section aria-labelledby="close-snapshot-title" className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2"><div><h2 id="close-snapshot-title" className="text-lg font-semibold">Month at a glance</h2><p className="muted">Amounts are shown in the original statement currency.</p></div><span className="text-xs text-muted-foreground">{month} · {currency}</span></div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Monthly reconciliation totals">
            <TotalCard icon={<Landmark />} label="Bank debits" value={amount(data.totals.bank_debits_cents / 100, currency)} help={`${data.transactions.length} imported debit transactions`} />
            <TotalCard icon={<FileSpreadsheet />} label="Accepted receipts" value={amount(data.totals.receipt_spend_cents / 100, currency)} help={`${data.receipts.length} receipts dated this month`} />
            <TotalCard icon={<CheckCircle2 />} label="Matched paid" value={amount(data.totals.matched_cents / 100, currency)} help={`${matchedPercent}% of accepted receipt spend`} tone="good" />
            <TotalCard icon={<AlertTriangle />} label="Needs attention" value={String(data.totals.exception_count)} help="Items to inspect below" tone={data.totals.exception_count ? "warn" : "good"} />
          </div>
        </section>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <section className="panel p-5 sm:p-6" aria-labelledby="coverage-title">
            <div className="flex items-center justify-between gap-3"><h3 id="coverage-title" className="font-semibold">Receipt coverage</h3><span className="rounded-full bg-emerald-50 px-3 py-1 text-sm font-semibold text-emerald-800 tabular-nums">{matchedPercent}% matched</span></div>
            <p className="muted mt-2">Accepted receipt value linked to a likely bank debit.</p>
            <div className="mt-5 h-2.5 overflow-hidden rounded-full bg-emerald-100" role="progressbar" aria-label="Accepted receipt spend matched to bank debits" aria-valuenow={matchedPercent} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-emerald-600 transition-[width] duration-500" style={{ width: `${matchedPercent}%` }} /></div>
            <p className="mt-5 border-t pt-4 text-sm"><span className="text-muted-foreground">Bank debits less accepted receipts</span><strong className="ml-2 tabular-nums">{amount(data.totals.difference_cents / 100, currency)}</strong></p>
          </section>
          <section className="panel p-5 sm:p-6" aria-labelledby="close-check-title">
            <h3 id="close-check-title" className="font-semibold">What needs checking</h3>
            <ul className="mt-3 divide-y text-sm">
              <li className="flex items-center justify-between gap-3 py-2"><span>Bank debits missing receipts</span><strong className={`rounded-full px-2.5 py-1 tabular-nums ${missingDebitCount ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-800"}`}>{missingDebitCount}</strong></li>
              <li className="flex items-center justify-between gap-3 py-2"><span>Receipts without a bank match</span><strong className={`rounded-full px-2.5 py-1 tabular-nums ${unmatchedReceiptCount ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-800"}`}>{unmatchedReceiptCount}</strong></li>
              <li className="flex items-center justify-between gap-3 py-2"><span>Possible duplicates</span><strong className={`rounded-full px-2.5 py-1 tabular-nums ${duplicateCount ? "bg-amber-50 text-amber-900" : "bg-emerald-50 text-emerald-800"}`}>{duplicateCount}</strong></li>
            </ul>
            <p className="mt-2 text-xs text-muted-foreground">Inspect the original records before recording a payment follow-up.</p>
          </section>
        </div>

        {!!data.statements.length && <section className="panel overflow-hidden" aria-label="Retained source statements">
          <div className="flex flex-wrap items-center gap-3 border-b bg-emerald-50/50 p-5"><span className="rounded-xl bg-white p-2.5 text-emerald-800"><FileText className="size-5" /></span><div><h2 className="font-semibold">Source statements <span className="font-normal text-muted-foreground">({data.statements.length})</span></h2><p className="muted">Open the retained original to check imported rows.</p></div></div>
          <div className="grid gap-3 p-4 sm:p-5">{data.statements.map((item) => <article key={item.statement_id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white p-4"><div className="min-w-0"><p className="truncate font-medium">{item.account_label}</p><p className="muted truncate">{item.original_filename} · {item.row_count} debits{item.imported_by ? ` · ${item.imported_by}` : ""}</p></div><div className="flex flex-wrap gap-2"><Button size="sm" variant={sourceStatement?.statement_id === item.statement_id ? "secondary" : "outline"} onClick={() => setSourceStatement(item)}><Eye /> View source</Button><Button size="sm" variant="ghost" aria-label={`Download ${item.original_filename}`} onClick={() => void downloadSource(item.statement_id, item.original_filename)}><Download /></Button>
            <Button size="sm" variant="ghost" className="text-red-700" onClick={() => setLifecycleTarget({ statement: item, restore: false })}>Remove</Button></div></article>)}</div>
        </section>}
        {!!data.removed_statements?.length && <details className="panel p-4">
          <summary className="cursor-pointer text-sm font-medium">Removed statements ({data.removed_statements.length})</summary>
          <p className="muted mt-2">Excluded from reconciliation. Sources and audit history are retained; restore an accidental removal here.</p>
          {data.removed_statements.map((item) => <div key={item.statement_id} className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3">
            <div><p className="font-medium">{item.account_label}</p><p className="muted">{item.original_filename} · {item.row_count} debits</p></div>
            <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => setSourceStatement(item)}>View source</Button>
              <Button size="sm" onClick={() => setLifecycleTarget({ statement: item, restore: true })}>Restore</Button></div>
          </div>)}
        </details>}
        <section id="close-evidence" className="scroll-mt-6 space-y-4" aria-labelledby="close-evidence-title">
          <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-xs font-semibold tracking-wide text-emerald-800 uppercase">Evidence review</p><h2 id="close-evidence-title" className="mt-1 text-lg font-semibold">Check the underlying records</h2><p className="muted">Compare debits to accepted receipts and open the originals when needed.</p></div><span className="text-xs text-muted-foreground">{month} · {currency}</span></div>
          <div className="panel flex flex-wrap items-center justify-between gap-3 bg-emerald-50/40 p-4" aria-label="Reconciliation filters">
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={exceptionsOnly} onChange={(event) => setExceptionsOnly(event.target.checked)} />Show items needing attention only</label>
            <label className="flex min-w-0 flex-wrap items-center gap-2 text-sm">Bank source <select aria-label="Filter bank transactions by source" className="h-10 w-full max-w-72 rounded-lg border bg-white px-2 sm:w-auto"
              value={data.statements.some((item) => item.statement_id === statementFilter) ? statementFilter : ""}
              onChange={(event) => setStatementFilter(event.target.value)}>
              <option value="">All active statements</option>{data.statements.map((item) => <option key={item.statement_id} value={item.statement_id}>{item.account_label} · {item.original_filename}</option>)}
            </select></label>
            <p className="w-full text-xs text-muted-foreground">Filters change the lists below. Summary totals and Excel exports still cover the whole month.</p>
          </div>
        <TransactionTable transactions={data.transactions.filter((item) => (!exceptionsOnly || item.status !== "MATCHED") && (!data.statements.some((source) => source.statement_id === statementFilter) || item.statement_id === statementFilter))} statements={data.statements} currency={currency} openReceipt={openReceiptFromMonth} viewSource={setSourceStatement} inspectMonth={(nextMonth) => openPeriod(nextMonth, currency)} />
        <section className="panel overflow-hidden" aria-labelledby="accepted-receipts-title">
          {exceptionsOnly && data.receipts.length > 0 && !data.receipts.some((item) => item.status !== "PAID" || item.duplicate_receipt) && <p className="muted p-4">No accepted receipts need attention in this period.</p>}
          <div className="border-b p-5 sm:p-6"><h3 id="accepted-receipts-title" className="text-lg font-semibold">Accepted receipts</h3><p className="muted mt-1">Open any accepted receipt in Ledgerly to compare its retained evidence and values. Record a payable or payment issue only after checking the bank and internal payment records.</p></div>
          {!data.receipts.length ? <p className="muted p-8 text-center">No accepted receipts are dated in this period.</p> : <div className="divide-y">{data.receipts.filter((item) => !exceptionsOnly || item.status !== "PAID" || item.duplicate_receipt).map((item) => <article key={item.receipt_id}>
            <div className="flex flex-wrap items-center justify-between gap-4 p-4 sm:px-6">
              <div className="min-w-0"><button className="text-left font-medium hover:underline" onClick={() => openReceiptFromMonth(item.receipt_id)}>{item.vendor}</button><p className="muted">{item.receipt_date} · {item.category}{item.duplicate_receipt ? " · possible duplicate receipt" : ""}</p>
                {item.adjacent_month_candidate && <button className="mt-1 text-sm font-medium text-amber-800 underline" onClick={() => openPeriod(item.adjacent_month_candidate!.month, currency)}>Possible debit in {item.adjacent_month_candidate.month} · inspect month</button>}
                {item.payment_event?.state === "TRADE_PAYABLE" && <p className="mt-1 text-xs text-muted-foreground">
                  {item.payment_event.invoice_due_date && <span className={item.payment_event.invoice_due_date < todayIso ? "font-semibold text-amber-800" : ""}>Invoice due {item.payment_event.invoice_due_date}{item.payment_event.invoice_due_date < todayIso ? " · date passed, verify payment" : ""}</span>}
                  {item.payment_event.planned_payment_date && <span className={item.payment_event.planned_payment_date < todayIso ? "font-semibold text-amber-800" : ""}> · Planned payment {item.payment_event.planned_payment_date}{item.payment_event.planned_payment_date < todayIso ? " · follow up" : ""}</span>}
                </p>}
              </div>
              <div className="flex flex-wrap items-center gap-3"><span className="font-semibold tabular-nums">{amount(item.amount_cents / 100, currency)}</span><Status value={item.duplicate_receipt ? "DUPLICATE_RECEIPT" : item.status} />{item.status !== "PAID" && <PaymentDialog token={token} receipt={item} saved={() => setRefresh((value) => value + 1)} />}<Button variant="ghost" onClick={() => openReceiptFromMonth(item.receipt_id)}>Open receipt <ArrowRight /></Button></div>
            </div>
            {!!item.payment_events?.length && <details className="group"><summary className="mx-4 mb-3 w-fit text-sm font-medium text-primary underline sm:mx-6">View payment-status history ({item.payment_events.length})</summary><PaymentHistory events={item.payment_events} compact /></details>}
          </article>)}</div>}
        </section>
        </section>

        <details className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-5"><summary className="cursor-pointer font-semibold text-emerald-950">Spending breakdown and review prompts <span className="ml-2 text-sm font-normal text-emerald-800">Optional analysis</span></summary><div className="mt-4 grid gap-4 xl:grid-cols-2">
          <Breakdown title="Highest expense categories" icon={<FileSpreadsheet />} items={data.categories.map((item) => ({ label: item.category, cents: item.total_cents }))} currency={currency} />
          <Breakdown title="Highest spend by company" icon={<Building2 />} items={data.vendors.map((item) => ({ label: item.vendor, cents: item.total_cents }))} currency={currency} />
        </div>

        <section className="rounded-xl border bg-white p-5 sm:p-6" aria-labelledby="insights-title">
          <div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-700"><Lightbulb className="size-5" /></span><div><h3 id="insights-title" className="font-semibold">Spending review prompts</h3><p className="muted">Simple rules based on this month’s accepted receipts, not AI advice</p></div></div>
          {data.suggestions.length ? <div className="mt-5 grid gap-3 lg:grid-cols-3">{data.suggestions.map((item) => <article key={item.title} className="rounded-xl border bg-muted/40 p-4"><h3 className="font-medium">{item.title}</h3><p className="muted mt-2">{item.detail}</p></article>)}</div> : <p className="muted mt-5">Add accepted receipts to generate grounded prompts.</p>}
          <p className="mt-4 text-xs text-muted-foreground">Supplier comparisons need current quotes and human review. Ledgerly does not claim a cheaper vendor without verified market evidence.</p>
        </section>
        </details>

        <details className="rounded-xl border bg-white p-4 text-sm text-muted-foreground"><summary className="flex items-center gap-2 font-medium text-foreground"><ShieldCheck className="size-4 text-emerald-700" /> Singapore record controls</summary><p className="mt-3 leading-6">Ledgerly keeps original receipt evidence, human decision history, payment follow-up events, and exportable monthly records. These controls support record keeping and PDPA accountability; they do not certify IRAS, GST, CPF, or PDPA compliance. Tax treatment and employee reimbursements still need your finance or HR reviewer.</p></details>
      </>}
      </>}
      <Dialog open={copilotOpen} onOpenChange={setCopilotOpen}>
        <DialogTrigger asChild>
          <button type="button" onClick={() => { if (view === "overview" && periods.length && !periods.some((period) => period.month === month && period.currency === currency)) { setMonth(periods[0].month); setCurrency(periods[0].currency); } }} className="copilot-launcher fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-2xl border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-950 shadow-xl transition hover:-translate-y-1 hover:shadow-2xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700 sm:right-6 sm:bottom-6" aria-label="Ask Finance Copilot">
            <CopilotAgent /><span className="max-sm:sr-only">Ask Finance Copilot</span>
          </button>
        </DialogTrigger>
        <DialogContent showCloseButton={false} className="!top-0 !right-0 !left-auto !h-[100dvh] !max-h-[100dvh] !w-full !max-w-[480px] !translate-x-0 !translate-y-0 !overflow-y-auto !rounded-none !border-0 !p-0 !shadow-2xl">
          <DialogTitle className="sr-only">Finance Copilot</DialogTitle>
          <DialogDescription className="sr-only">Read-only guidance using the selected monthly reconciliation.</DialogDescription>
          <div className="flex items-center justify-between border-b bg-white px-5 py-3">
            <p className="text-sm font-medium text-emerald-950">Monthly Close · {view === "detail" ? month : periods[0]?.month ?? month}</p>
            <DialogClose asChild><Button variant="ghost" size="sm" aria-label="Close Finance Copilot"><X /></Button></DialogClose>
          </div>
          {view === "overview" && !!periods.length && <div className="px-5 pt-3"><label htmlFor="copilot-period" className="field-label">Period to discuss</label><select id="copilot-period" className="h-10 w-full rounded-lg border bg-white px-3" value={`${month}|${currency}`} onChange={(event) => { const [selectedMonth, selectedCurrency] = event.target.value.split("|"); setMonth(selectedMonth); setCurrency(selectedCurrency); }}><option value={`${month}|${currency}`}>{month} · {currency}</option>{periods.filter((period) => `${period.month}|${period.currency}` !== `${month}|${currency}`).map((period) => <option key={`${period.month}|${period.currency}`} value={`${period.month}|${period.currency}`}>{period.month} · {period.currency}</option>)}</select></div>}
          <FinanceCopilot key={`${month}-${currency}-${refresh}`} compact token={token} month={month} currency={currency} exceptionCount={view === "detail" ? data?.totals.exception_count ?? 0 : periods.find((period) => period.month === month && period.currency === currency)?.exception_count ?? 0} matchedPercent={view === "detail" && data ? matchedPercent : null} statementCount={view === "detail" ? data?.statements.length ?? 0 : periods.find((period) => period.month === month && period.currency === currency)?.statement_count ?? 0} receiptIds={view === "detail" ? data?.receipts.map((receipt) => receipt.receipt_id) ?? [] : []} openReceipt={(id) => { setCopilotOpen(false); openReceiptFromMonth(id); }} />
        </DialogContent>
      </Dialog>
      {reviewOpen && data && <MonthReviewDialog token={token} data={data} close={() => setReviewOpen(false)} saved={() => { setReviewOpen(false); setSuccess("Monthly review recorded. It will be flagged if the evidence changes."); setRefresh((value) => value + 1); }} />}
      {lifecycleTarget && <StatementLifecycleDialog key={lifecycleTarget.statement.statement_id} token={token} target={lifecycleTarget}
        close={() => setLifecycleTarget(null)} saved={() => {
          setSuccess(lifecycleTarget.restore ? "Statement restored. Reconciliation has been recalculated." : "Statement removed from reconciliation. Receipts are unchanged. You can restore it below.");
          setLifecycleTarget(null); setSourceStatement(null); setStatementFilter(""); setData(null);
          setRefresh((value) => value + 1);
        }} />}
      {sourceStatement && <StatementSourcePanel key={sourceStatement.statement_id} token={token} statement={sourceStatement} onClose={() => setSourceStatement(null)} download={() => void downloadSource(sourceStatement.statement_id, sourceStatement.original_filename)} />}
    </div>
  );
}

function MonthReviewDialog({ token, data, close, saved }: { token: string; data: Reconciliation; close: () => void; saved: () => void }) {
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await request("/reconciliation/reviews", token, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ month: data.month, currency: data.currency, actor: actor.trim(), note: note.trim(), fingerprint: data.review.fingerprint }) });
      saved();
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <Dialog open onOpenChange={(next) => { if (!next) close(); }}><DialogContent><DialogHeader><DialogTitle>Record monthly review</DialogTitle><DialogDescription>Confirm you checked the bank source and accepted receipts for {data.month} · {data.currency}. This records your review; it does not change any receipt or bank transaction.</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div><label className="field-label" htmlFor="month-reviewer">Reviewer name</label><Input id="month-reviewer" required minLength={2} maxLength={100} value={actor} onChange={(e) => setActor(e.target.value)} /></div><div><label className="field-label" htmlFor="month-review-note">Review notes or actions remaining</label><Textarea id="month-review-note" required minLength={5} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Record unresolved evidence and the next check" /></div>{data.totals.exception_count > 0 && <Notice variant="warning">{data.totals.exception_count} exceptions remain. Record how they will be followed up; the overview will continue to flag them.</Notice>}<label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I checked the retained bank source and receipt evidence for this month.</label>{error && <Notice variant="destructive">{error}</Notice>}<DialogFooter><Button type="button" variant="outline" onClick={close}>Cancel</Button><Button type="submit" disabled={busy || !confirmed || actor.trim().length < 2 || note.trim().length < 5}>{busy && <LoaderCircle className="animate-spin" />}Record review</Button></DialogFooter></form></DialogContent></Dialog>;
}

type StatementPreview = {
  statement_month: string; currency: string; account_label: string; imported_by: string;
  extraction_method: "deterministic" | "ai"; text_engine: string;
  metadata: { bank_name: string | null; account_last_four: string | null; opening_balance_cents: number | null; closing_balance_cents: number | null };
  validation: { balance_reconciled: boolean | null; confirmable: boolean; warnings: string[]; credits_skipped: number; credit_total_cents: number; calculated_closing_balance_cents: number | null; balance_difference_cents: number | null; outside_month: number };
  transactions: { posted_date: string; description: string; amount_cents: number; reference: string | null; source_row: number }[];
  transactions_imported: number; debit_total_cents: number;
};

function StatementUpload({ token, completed }: { token: string; completed: (month: string, currency: string) => void }) {
  const [open, setOpen] = useState(false), [file, setFile] = useState<File | null>(null), [month, setMonth] = useState(currentMonth), [currency, setCurrency] = useState("SGD"), [account, setAccount] = useState("Operating account"), [importer, setImporter] = useState(""), [password, setPassword] = useState(""), [allowAi, setAllowAi] = useState(false), [confirmed, setConfirmed] = useState(false), [preview, setPreview] = useState<StatementPreview | null>(null), [confirmationToken, setConfirmationToken] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const isPdf = file?.name.toLowerCase().endsWith(".pdf") || false;
  function resetPreview() { setPreview(null); setConfirmationToken(""); setConfirmed(false); }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if (!file || !/\.(csv|pdf)$/i.test(file.name)) { setError("Choose a PDF or CSV bank statement."); return; }
    if ((!isPdf && file.size > 2 * 1024 * 1024) || (isPdf && file.size > 10 * 1024 * 1024)) { setError(isPdf ? "Choose a PDF up to 10 MB." : "Choose a CSV up to 2 MB."); return; }
    setBusy(true);
    const body = new FormData(); body.set("statement", file); body.set("statement_month", month); body.set("currency", currency); body.set("account_label", account.trim()); body.set("imported_by", importer.trim());
    try {
      if (!isPdf) {
        await request("/bank-statements/upload", token, { method: "POST", body });
        setOpen(false); setFile(null); completed(month, currency); return;
      }
      if (password) body.set("password", password);
      body.set("allow_ai", String(allowAi));
      const result = await request<{ preview: StatementPreview; confirmation_token: string }>("/bank-statements/preview", token, { method: "POST", body, timeoutMs: 180000 });
      setPreview(result.preview); setConfirmationToken(result.confirmation_token); setPassword("");
    }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  async function confirmImport() {
    if (!file || !preview || !confirmationToken || !confirmed) return;
    setBusy(true); setError("");
    const body = new FormData(); body.set("statement", file); body.set("preview_json", JSON.stringify(preview)); body.set("confirmation_token", confirmationToken); body.set("evidence_confirmed", "true");
    try { await request("/bank-statements/confirm", token, { method: "POST", body, timeoutMs: 60000 }); setOpen(false); setFile(null); resetPreview(); completed(preview.statement_month, preview.currency); }
    catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  function downloadTemplate() {
    const blob = new Blob(["Date,Description,Debit,Reference\n2026-09-03,Example supplier,125.40,TXN-001\n"], { type: "text/csv" });
    const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "ledgerly-bank-statement-template.csv"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Dialog open={open} onOpenChange={(next) => { setOpen(next); if (!next) { setPassword(""); resetPreview(); } }}>
      <DialogTrigger asChild><Button><Upload /> Upload statement</Button></DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{preview ? "Confirm extracted statement" : "Upload monthly bank statement"}</DialogTitle>
          <DialogDescription>{preview ? "Check the extracted debits against the original PDF before anything is retained." : "Upload the bank-issued PDF, or use a normalized UTF-8 CSV fallback."}</DialogDescription>
        </DialogHeader>
        {!preview ? (
          <form onSubmit={submit} className="space-y-4">
            <div className="rounded-lg border border-dashed bg-muted p-4">
              <label htmlFor="statement-file" className="field-label">Statement PDF or CSV</label>
              <Input id="statement-file" type="file" accept=".pdf,application/pdf,.csv,text/csv" required disabled={busy} onChange={(e) => { setFile(e.target.files?.[0] || null); resetPreview(); setError(""); }} />
              <button type="button" onClick={downloadTemplate} className="mt-2 text-sm font-medium text-primary hover:underline">Download CSV template</button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label htmlFor="statement-month" className="field-label">Statement month</label><Input id="statement-month" type="month" required value={month} onChange={(e) => setMonth(e.target.value)} /></div>
              <div><label htmlFor="statement-currency" className="field-label">Currency</label><Input id="statement-currency" required minLength={3} maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label htmlFor="account-label" className="field-label">Account label</label><Input id="account-label" required minLength={2} maxLength={100} value={account} onChange={(e) => setAccount(e.target.value)} /></div>
              <div><label htmlFor="statement-importer" className="field-label">Imported by</label><Input id="statement-importer" required minLength={2} maxLength={100} value={importer} onChange={(e) => setImporter(e.target.value)} placeholder="Your name" /></div>
            </div>
            {isPdf && <>
              <div>
                <label htmlFor="statement-password" className="field-label">PDF password <span className="font-normal text-muted-foreground">(only if encrypted)</span></label>
                <Input id="statement-password" type="password" autoComplete="off" maxLength={200} value={password} onChange={(e) => setPassword(e.target.value)} />
                <p className="mt-1 text-xs text-muted-foreground">Used in memory for this preview only; never saved or sent to the AI gateway.</p>
              </div>
              <label className="flex items-start gap-3 rounded-lg border p-3 text-sm">
                <input type="checkbox" className="mt-1" checked={allowAi} onChange={(e) => setAllowAi(e.target.checked)} />
                <span><strong className="block">Allow AI fallback for an unfamiliar layout</strong><span className="text-muted-foreground">If deterministic parsing fails, obvious account numbers are masked before extracted statement text—including company and counterparty details—is sent to the configured AI gateway. This may consume credits.</span></span>
              </label>
            </>}
            <Notice variant="info">PDFs are previewed before import. The private parser expects readable transaction dates and debit, credit and balance columns; other layouts may require explicit AI consent or a normalized CSV. CSV files use the deterministic importer. Original files are retained only after import.</Notice>
            {error && <Notice variant="destructive">{error}</Notice>}
            <DialogFooter><Button type="submit" disabled={busy || !file || importer.trim().length < 2}>{busy ? <LoaderCircle className="animate-spin" /> : <Upload />}{busy ? "Reading statement…" : isPdf ? "Preview statement" : "Import CSV"}</Button></DialogFooter>
          </form>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border p-3"><p className="field-label">Detected source</p><p className="font-medium">{preview.metadata.bank_name || "Bank not identified"}{preview.metadata.account_last_four ? ` · •••• ${preview.metadata.account_last_four}` : ""}</p><p className="muted">{preview.extraction_method === "ai" ? "AI-assisted extraction" : "Private deterministic extraction"}</p></div>
              <div className="rounded-lg border p-3"><p className="field-label">Debits found</p><p className="text-xl font-semibold">{preview.transactions_imported}</p><p className="muted">{preview.validation.credits_skipped} credit row(s) excluded</p></div>
              <div className="rounded-lg border p-3"><p className="field-label">Debit total</p><p className="text-xl font-semibold tabular-nums">{amount(preview.debit_total_cents / 100, preview.currency)}</p><p className="muted">{preview.statement_month} · {preview.currency}</p></div>
            </div>
            {preview.validation.balance_reconciled === true && <Notice variant="info">Opening balance plus credits less debits agrees with the closing balance.</Notice>}
            {preview.validation.balance_reconciled === false && <Notice variant="destructive">The balances do not reconcile. This preview is blocked from import; obtain a CSV export or check the statement layout.</Notice>}
            {preview.metadata.opening_balance_cents !== null && preview.metadata.closing_balance_cents !== null && <div className={`rounded-xl border p-4 text-sm ${preview.validation.balance_reconciled === false ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50/60"}`} aria-label="Statement balance calculation"><p className="font-semibold">Balance cross-check</p><p className="mt-2 tabular-nums">Opening {amount(preview.metadata.opening_balance_cents / 100, preview.currency)} + credits {amount(preview.validation.credit_total_cents / 100, preview.currency)} − debits {amount(preview.debit_total_cents / 100, preview.currency)} = calculated closing {amount((preview.validation.calculated_closing_balance_cents ?? 0) / 100, preview.currency)}</p><p className="mt-1 tabular-nums">Statement closing: {amount(preview.metadata.closing_balance_cents / 100, preview.currency)}{preview.validation.balance_difference_cents !== null ? ` · Difference: ${amount(preview.validation.balance_difference_cents / 100, preview.currency)}` : ""}</p>{preview.validation.balance_reconciled === false && <p className="mt-2">Compare each extracted row and all credits against the PDF. If the layout was misread, use the bank's CSV export. Enabling AI does not override this balance check.</p>}</div>}
            {preview.validation.warnings.map((warning) => <Notice key={warning} variant="warning">{warning}</Notice>)}
            <div className="max-h-72 overflow-auto rounded-lg border">
              <table className="w-full text-left text-sm"><thead className="sticky top-0 bg-muted"><tr><th className="p-3">Date</th><th className="p-3">Description</th><th className="p-3 text-right">Debit</th></tr></thead><tbody>{preview.transactions.map((item, index) => <tr key={`${item.source_row}-${index}`} className="border-t"><td className="whitespace-nowrap p-3">{item.posted_date}</td><td className="p-3">{item.description}</td><td className="whitespace-nowrap p-3 text-right tabular-nums">{amount(item.amount_cents / 100, preview.currency)}</td></tr>)}</tbody></table>
            </div>
            <label className="flex items-start gap-3 rounded-lg border p-3 text-sm"><input type="checkbox" className="mt-1" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /><span><strong className="block">I checked the extracted debits against the original PDF</strong><span className="text-muted-foreground">Importing retains the original statement and uses these rows for reconciliation; it does not initiate payments.</span></span></label>
            {error && <Notice variant="destructive">{error}</Notice>}
            <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={resetPreview}>Back</Button><Button type="button" disabled={busy || !confirmed || !preview.validation.confirmable} onClick={() => void confirmImport()}>{busy && <LoaderCircle className="animate-spin" />}Confirm and import</Button></DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PaymentDialog({ token, receipt, saved }: { token: string; receipt: ReceiptRow; saved: () => void }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState(receipt.payment_event?.state === "TRADE_PAYABLE" ? "TRADE_PAYABLE" : "PAYMENT_ISSUE");
  const [actor, setActor] = useState("");
  const [note, setNote] = useState("");
  const [invoiceDue, setInvoiceDue] = useState(receipt.payment_event?.state === "TRADE_PAYABLE" ? receipt.payment_event.invoice_due_date ?? "" : "");
  const [plannedPayment, setPlannedPayment] = useState(receipt.payment_event?.state === "TRADE_PAYABLE" ? receipt.payment_event.planned_payment_date ?? "" : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await request(`/receipts/${receipt.receipt_id}/payment-state`, token, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state, actor, note, expected_version: receipt.payment_event?.version ?? 0,
          ...(state === "TRADE_PAYABLE" ? { invoice_due_date: invoiceDue || null, planned_payment_date: plannedPayment || null } : {}) }),
      });
      setOpen(false); saved();
    } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="outline">Update status</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Record payment follow-up</DialogTitle><DialogDescription>This adds an audit event for {receipt.vendor}. Check bank records first; this action does not move money.</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4">
    <div><label htmlFor="payment-state" className="field-label">Status</label><select id="payment-state" className="h-10 w-full rounded-md border bg-white px-3" value={state} onChange={(e) => setState(e.target.value)}><option value="TRADE_PAYABLE">Trade payable — valid amount still due</option><option value="PAYMENT_ISSUE">Payment issue — attempted or blocked</option><option value="CLEAR">Clear manual status</option></select></div>
    {state === "TRADE_PAYABLE" && <div className="grid gap-3 sm:grid-cols-2"><div><label htmlFor="invoice-due" className="field-label">Invoice due date (optional)</label><Input id="invoice-due" type="date" value={invoiceDue} onChange={(e) => setInvoiceDue(e.target.value)} /></div><div><label htmlFor="planned-payment" className="field-label">Planned payment date (optional)</label><Input id="planned-payment" type="date" value={plannedPayment} onChange={(e) => setPlannedPayment(e.target.value)} /></div><p className="muted sm:col-span-2">These are follow-up dates only. A plan never marks a receipt paid.</p></div>}
    <div><label htmlFor="payment-actor" className="field-label">Recorded by</label><Input id="payment-actor" required minLength={2} maxLength={100} value={actor} onChange={(e) => setActor(e.target.value)} /></div>
    <div><label htmlFor="payment-note" className="field-label">Evidence and next step</label><Textarea id="payment-note" required minLength={5} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: payment scheduled for Friday; verify bank debit and beneficiary." /></div>
    {error && <Notice variant="destructive">{error}</Notice>}<DialogFooter><Button disabled={busy}>{busy && <LoaderCircle className="animate-spin" />}Save audit event</Button></DialogFooter>
  </form></DialogContent></Dialog>;
}

function TotalCard({ icon, label, value, help, tone = "plain" }: { icon: React.ReactNode; label: string; value: string; help: string; tone?: "plain" | "good" | "warn" }) {
  const tones = {
    plain: { accent: "border-t-slate-300", icon: "bg-slate-100 text-slate-700" },
    good: { accent: "border-t-emerald-600", icon: "bg-emerald-50 text-emerald-700" },
    warn: { accent: "border-t-amber-500", icon: "bg-amber-50 text-amber-800" },
  };
  const style = tones[tone];
  return <article className={`panel border-t-4 p-5 ${style.accent}`}>
    <div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-muted-foreground">{label}</p><p className="mt-2 text-2xl font-semibold tabular-nums">{value}</p></div><span className={`rounded-xl p-2.5 [&>svg]:size-5 ${style.icon}`}>{icon}</span></div>
    <p className="muted mt-2">{help}</p>
  </article>;
}
function Breakdown({ title, icon, items, currency }: { title: string; icon: React.ReactNode; items: { label: string; cents: number }[]; currency: string }) { const max = Math.max(1, ...items.map((item) => item.cents)); return <section className="rounded-xl border bg-white p-5 sm:p-6"><div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-700">{icon}</span><h3 className="font-semibold">{title}</h3></div>{!items.length ? <p className="muted py-8 text-center">No accepted receipt spend for this period.</p> : <ol className="mt-5 space-y-4">{items.slice(0, 5).map((item, index) => <li key={item.label}><div className="mb-1.5 flex justify-between gap-3 text-sm"><span className="truncate"><span className="mr-2 text-muted-foreground">{index + 1}</span>{item.label}</span><strong className="shrink-0 tabular-nums">{amount(item.cents / 100, currency)}</strong></div><div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(3, item.cents / max * 100)}%` }} /></div></li>)}</ol>}</section>; }

function TransactionTable({ transactions, statements, currency, openReceipt, viewSource, inspectMonth }: {
  transactions: Transaction[]; statements: StatementRecord[]; currency: string;
  openReceipt: (id: string) => void; viewSource: (statement: StatementRecord) => void;
  inspectMonth: (month: string) => void;
}) {
  return <section className="panel overflow-hidden" aria-labelledby="transactions-title">
    <div className="border-b p-5 sm:p-6"><h3 id="transactions-title" className="text-lg font-semibold">Imported bank debits</h3><p className="muted mt-1">Compare each debit with the retained statement and accepted receipt. Possible matches in neighboring months need your review.</p></div>
    {!transactions.length ? <p className="muted p-8 text-center">No imported debits are available for this period.</p> : <div className="overflow-x-auto"><table className="w-full min-w-[820px] text-left text-sm"><thead className="bg-muted/70"><tr><th className="p-3 pl-6">Date</th><th className="p-3">Description</th><th className="p-3 text-right">Debit</th><th className="p-3">Status</th><th className="p-3 pr-6 text-right">Evidence</th></tr></thead><tbody>{transactions.map((item) => {
      const statement = statements.find((candidate) => candidate.statement_id === item.statement_id);
      return <tr key={item.transaction_id} className={`border-t ${item.status === "MATCHED" ? "" : "bg-amber-50/40"}`}><td className="whitespace-nowrap p-3 pl-6">{item.posted_date}</td><td className="p-3"><p className="font-medium">{item.description}</p>{item.reference && <p className="muted">Ref {item.reference}</p>}{item.adjacent_month_candidate && <button className="mt-1 text-xs font-medium text-amber-800 underline" onClick={() => inspectMonth(item.adjacent_month_candidate!.month)}>Possible receipt in {item.adjacent_month_candidate.month} · inspect month</button>}</td><td className="whitespace-nowrap p-3 text-right font-semibold tabular-nums">{amount(item.amount_cents / 100, currency)}</td><td className="p-3"><Status value={item.status} /></td><td className="p-3 pr-6"><div className="flex justify-end gap-2">{statement && <Button size="sm" variant="outline" onClick={() => viewSource(statement)}><FileText /> Statement</Button>}{item.receipt_id && <Button size="sm" variant="ghost" onClick={() => openReceipt(item.receipt_id!)}>Receipt <ArrowRight /></Button>}</div></td></tr>;
    })}</tbody></table></div>}
  </section>;
}

function StatementSourcePanel({ token, statement, onClose, download }: { token: string; statement: StatementRecord; onClose: () => void; download: () => void }) {
  const [previewUrl, setPreviewUrl] = useState("");
  const [csvText, setCsvText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const isPdf =
    statement.source_media_type === "application/pdf" ||
    statement.original_filename.toLowerCase().endsWith(".pdf");

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl = "";
    const endpoint = isPdf
      ? `/bank-statements/${statement.statement_id}/source-preview`
      : `/bank-statements/${statement.statement_id}/source`;
    fetch(endpoint, {
      headers: authenticationHeaders(token),
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            isPdf
              ? "The statement preview could not be rendered. Download the original source instead."
              : "The retained source statement could not be opened.",
          );
        }
        const blob = await response.blob();
        if (isPdf) {
          objectUrl = URL.createObjectURL(blob);
          setPreviewUrl(objectUrl);
        } else {
          setCsvText(await blob.text());
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) setError(message(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [isPdf, statement, token]);

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-labelledby="statement-source-title"
      className="fixed inset-y-3 right-3 z-50 flex w-[calc(100vw-1.5rem)] flex-col overflow-hidden rounded-2xl border bg-background shadow-2xl lg:w-[min(48rem,48vw)]"
    >
      <header className="flex items-start justify-between gap-4 border-b p-4">
        <div className="min-w-0">
          <p className="field-label">Statement source</p>
          <h2 id="statement-source-title" className="truncate text-lg font-semibold">
            {statement.account_label}
          </h2>
          <p className="muted truncate">
            {statement.original_filename} · read-only evidence
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={download}>
            <Download /> Download
          </Button>
          <Button
            size="icon-sm"
            variant="ghost"
            aria-label="Close statement source"
            onClick={onClose}
          >
            <X />
          </Button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-auto bg-muted/30 p-3">
        {busy ? (
          <div role="status" className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="animate-spin" /> Loading retained source…
          </div>
        ) : error ? (
          <div className="space-y-3">
            <Notice variant="destructive">{error}</Notice>
            <Button variant="outline" onClick={download}>
              <Download /> Download original
            </Button>
          </div>
        ) : previewUrl ? (
          <div className="rounded-lg border bg-white p-2">
            <img
              src={previewUrl}
              alt={`First page of ${statement.original_filename}`}
              className="mx-auto h-auto max-w-full"
            />
          </div>
        ) : (
          <pre
            className="min-h-[70vh] overflow-auto rounded-lg border bg-white p-4 text-xs leading-6 whitespace-pre"
            tabIndex={0}
          >
            {csvText}
          </pre>
        )}
      </div>
      <footer className="border-t px-4 py-3 text-xs text-muted-foreground">
        {isPdf
          ? "Safe first-page image preview. Download the retained original to review every page."
          : "Compare the retained CSV with the imported debit table."}
      </footer>
    </aside>
  );
}
function MonthlySkeleton() { return <div role="status" aria-label="Loading monthly close" className="space-y-5 animate-pulse"><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0,1,2,3].map((item) => <div key={item} className="h-32 rounded-xl bg-muted" />)}</div><div className="h-48 rounded-xl bg-muted" /><span className="sr-only">Loading monthly close…</span></div>; }


function StatementLifecycleDialog({ token, target, close, saved }: {
  token: string; target: { statement: StatementRecord; restore: boolean }; close: () => void; saved: () => void;
}) {
  const [actor, setActor] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      await request(`/bank-statements/${target.statement.statement_id}/lifecycle`, token, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: target.restore ? "RESTORE" : "REMOVE", actor: actor.trim(), reason: reason.trim() }),
      });
      saved();
    } catch (caught) { setError(message(caught)); }
    finally { setBusy(false); }
  }
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}>
    <DialogContent><DialogHeader><DialogTitle>{target.restore ? "Restore" : "Remove"} statement?</DialogTitle>
      <DialogDescription>{target.statement.account_label} · {target.statement.original_filename}</DialogDescription></DialogHeader>
      <p className="text-sm">{target.restore ? "This restores the statement and recalculates its bank matches." :
        `This excludes ${target.statement.row_count} imported debits and recalculates matches. Receipts and payment notes are not deleted. The original source is retained so removal can be reversed.`}</p>
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm">Your name<Input required minLength={2} maxLength={100} value={actor} disabled={busy} onChange={(event) => setActor(event.target.value)} /></label>
        <label className="block text-sm">Reason<Textarea required minLength={5} maxLength={500} value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} placeholder={target.restore ? "Why should this statement be restored?" : "For example: wrong account or incorrect source uploaded"} /></label>
        {error && <Notice variant="destructive">{error}</Notice>}
        <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={close}>Cancel</Button>
          <Button type="submit" disabled={busy || actor.trim().length < 2 || reason.trim().length < 5}>{busy ? "Saving…" : target.restore ? "Restore statement" : "Remove statement"}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
