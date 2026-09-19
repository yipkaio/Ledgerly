import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  Landmark,
  Lightbulb,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Notice, Status } from "@/components/feedback";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { amount, message, request, requestDownload } from "@/lib/api";

type Period = { month: string; currency: string; statement_count: number; transaction_count: number };
type Transaction = {
  transaction_id: string; posted_date: string; description: string; amount_cents: number;
  reference: string | null; receipt_id: string | null; receipt_vendor: string | null; status: string;
};
type ReceiptRow = {
  receipt_id: string; receipt_date: string; vendor: string; category: string; amount_cents: number;
  status: string; transaction_id: string | null; duplicate_receipt: boolean;
};
type Reconciliation = {
  month: string; currency: string;
  statements: { statement_id: string; account_label: string; original_filename: string; uploaded_at: string; row_count: number; skipped_rows: number; source_media_type?: string; extraction_method?: string; imported_by?: string }[];
  transactions: Transaction[]; receipts: ReceiptRow[];
  totals: { bank_debits_cents: number; receipt_spend_cents: number; matched_cents: number; difference_cents: number; exception_count: number };
  categories: { category: string; total_cents: number }[];
  vendors: { vendor: string; total_cents: number }[];
  suggestions: { title: string; detail: string }[];
  generated_at: string;
};

const currentMonth = new Date().toISOString().slice(0, 7);

export function MonthlyClose({ token, openReceipt }: { token: string; openReceipt: (id: string) => void }) {
  const [periods, setPeriods] = useState<Period[]>([]);
  const [month, setMonth] = useState(currentMonth);
  const [currency, setCurrency] = useState("SGD");
  const [data, setData] = useState<Reconciliation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [exportBusy, setExportBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    request<{ items: Period[] }>("/bank-statements/periods", token, { signal: controller.signal })
      .then((result) => {
        if (controller.signal.aborted) return;
        setPeriods(result.items);
        if (result.items.length && refresh === 0) {
          setMonth(result.items[0].month);
          setCurrency(result.items[0].currency);
        }
      })
      .catch((e) => !controller.signal.aborted && setError(message(e)));
    return () => controller.abort();
  }, [token, refresh]);

  useEffect(() => {
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Reset status for this cancellable API read.
    setBusy(true); setError("");
    request<Reconciliation>(`/reconciliation?month=${month}&currency=${currency}`, token, { signal: controller.signal })
      .then((result) => !controller.signal.aborted && setData(result))
      .catch((e) => !controller.signal.aborted && setError(message(e)))
      .finally(() => !controller.signal.aborted && setBusy(false));
    return () => controller.abort();
  }, [token, month, currency, refresh]);

  const periodValue = `${month}|${currency}`;
  const matchedPercent = data?.totals.receipt_spend_cents
    ? Math.min(100, Math.round((data.totals.matched_cents / data.totals.receipt_spend_cents) * 100)) : 0;
  const transactionExceptions = useMemo(() => data?.transactions.filter((item) => item.status !== "MATCHED") || [], [data]);
  const receiptExceptions = useMemo(() => data?.receipts.filter((item) => item.status !== "PAID" || item.duplicate_receipt) || [], [data]);

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
        headers: { "X-API-Key": token }, cache: "no-store", signal: AbortSignal.timeout(30000),
      });
      if (!response.ok) throw new Error("The source statement could not be downloaded.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError(message(e)); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <p className="muted">Match bank debits to accepted receipts, record payment follow-up, and close each month with clear evidence.</p>
          <p className="mt-2 text-xs text-muted-foreground">Matches are suggestions based on amount, date, and vendor text. Review exceptions before relying on the totals.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatementUpload token={token} completed={(nextMonth, nextCurrency) => { setMonth(nextMonth); setCurrency(nextCurrency); setRefresh((value) => value + 1); }} />
          <Button variant="outline" disabled={!data || exportBusy} onClick={() => void exportMonth()}>
            {exportBusy ? <LoaderCircle className="animate-spin" /> : <Download />} Export month
          </Button>
          <Button variant="ghost" onClick={() => setRefresh((value) => value + 1)}><RefreshCw /> Refresh</Button>
        </div>
      </div>

      <section className="panel flex flex-wrap items-end gap-4 p-4" aria-label="Reconciliation period">
        <div className="min-w-56 flex-1">
          <label htmlFor="close-period" className="field-label">Statement period</label>
          <select id="close-period" className="h-10 w-full rounded-md border bg-white px-3" value={periodValue}
            onChange={(event) => { const [nextMonth, nextCurrency] = event.target.value.split("|"); setMonth(nextMonth); setCurrency(nextCurrency); }}>
            {!periods.some((item) => `${item.month}|${item.currency}` === periodValue) && <option value={periodValue}>{month} · {currency} · no statement</option>}
            {periods.map((item) => <option key={`${item.month}-${item.currency}`} value={`${item.month}|${item.currency}`}>{item.month} · {item.currency} · {item.transaction_count} debits</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="manual-month" className="field-label">Check another month</label>
          <Input id="manual-month" type="month" value={month} onChange={(event) => setMonth(event.target.value)} />
        </div>
        <div>
          <label htmlFor="manual-currency" className="field-label">Currency</label>
          <Input id="manual-currency" maxLength={3} className="w-28" value={currency} onChange={(event) => setCurrency(event.target.value.toUpperCase())} />
        </div>
      </section>

      {error && <Notice variant="destructive">{error}</Notice>}
      {busy ? <MonthlySkeleton /> : data && <>
        {!data.statements.length && <Notice variant="warning">No {currency} statement is loaded for {month}. Accepted receipts are still shown so you can see what needs a bank match.</Notice>}
        {!!data.statements.length && <section className="panel flex flex-wrap items-center justify-between gap-4 p-4 sm:px-5" aria-label="Retained source statements"><div><p className="font-medium">{data.statements.length} source statement{data.statements.length === 1 ? "" : "s"} retained</p><p className="muted">Original PDF or CSV evidence remains available with the normalized transactions.</p></div><div className="flex flex-wrap gap-2">{data.statements.map((item) => <Button key={item.statement_id} variant="outline" onClick={() => void downloadSource(item.statement_id, item.original_filename)}><Download /> {item.account_label} · {item.row_count} rows{item.imported_by ? ` · ${item.imported_by}` : ""}</Button>)}</div></section>}
        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Monthly reconciliation totals">
          <TotalCard icon={<Landmark />} label="Bank debits" value={amount(data.totals.bank_debits_cents / 100, currency)} help={`${data.transactions.length} imported debit transactions`} />
          <TotalCard icon={<FileSpreadsheet />} label="Accepted receipts" value={amount(data.totals.receipt_spend_cents / 100, currency)} help={`${data.receipts.length} receipts dated this month`} />
          <TotalCard icon={<CheckCircle2 />} label="Matched paid" value={amount(data.totals.matched_cents / 100, currency)} help={`${matchedPercent}% of accepted receipt spend`} tone="good" />
          <TotalCard icon={<AlertTriangle />} label="Needs attention" value={String(data.totals.exception_count)} help={`Bank less receipts: ${amount(data.totals.difference_cents / 100, currency)}`} tone={data.totals.exception_count ? "warn" : "good"} />
        </section>

        <section className="panel overflow-hidden" aria-labelledby="coverage-title">
          <div className="flex flex-wrap items-center justify-between gap-4 p-5 sm:p-6">
            <div><h2 id="coverage-title" className="text-lg font-semibold">Reconciliation coverage</h2><p className="muted mt-1">Accepted receipt value linked to a likely bank debit</p></div>
            <span className="text-2xl font-semibold tabular-nums">{matchedPercent}%</span>
          </div>
          <div className="h-3 bg-muted"><div className="h-full bg-emerald-600 transition-[width] duration-500" style={{ width: `${matchedPercent}%` }} /></div>
        </section>

        <div className="grid gap-6 xl:grid-cols-2">
          <Breakdown title="Highest expense categories" icon={<FileSpreadsheet />} items={data.categories.map((item) => ({ label: item.category, cents: item.total_cents }))} currency={currency} />
          <Breakdown title="Highest spend by company" icon={<Building2 />} items={data.vendors.map((item) => ({ label: item.vendor, cents: item.total_cents }))} currency={currency} />
        </div>

        <section className="panel p-5 sm:p-6" aria-labelledby="insights-title">
          <div className="flex items-center gap-3"><span className="rounded-xl bg-violet-50 p-2.5 text-violet-700"><Lightbulb className="size-5" /></span><div><h2 id="insights-title" className="font-semibold">Cost-saving prompts</h2><p className="muted">Grounded in this month’s accepted receipts</p></div></div>
          {data.suggestions.length ? <div className="mt-5 grid gap-3 lg:grid-cols-3">{data.suggestions.map((item) => <article key={item.title} className="rounded-xl border bg-muted/40 p-4"><h3 className="font-medium">{item.title}</h3><p className="muted mt-2">{item.detail}</p></article>)}</div> : <p className="muted mt-5">Add accepted receipts to generate grounded prompts.</p>}
          <p className="mt-4 text-xs text-muted-foreground">Supplier comparisons need current quotes and human review. Ledgerly does not claim a cheaper vendor without verified market evidence.</p>
        </section>

        <ExceptionTable title="Bank transactions to review" empty="Every imported debit has a likely receipt match." rows={transactionExceptions.map((item) => ({ id: item.transaction_id, primary: item.description, secondary: item.posted_date, cents: item.amount_cents, status: item.status }))} currency={currency} />
        <section className="panel overflow-hidden" aria-labelledby="receipt-exceptions-title">
          <div className="border-b p-5 sm:p-6"><h2 id="receipt-exceptions-title" className="text-lg font-semibold">Receipt payment follow-up</h2><p className="muted mt-1">Record a payable or payment issue only after checking the bank and internal payment records.</p></div>
          {!receiptExceptions.length ? <p className="muted p-8 text-center">Every accepted receipt has a likely bank match.</p> : <div className="divide-y">{receiptExceptions.map((item) => <div key={item.receipt_id} className="flex flex-wrap items-center justify-between gap-4 p-4 sm:px-6"><div className="min-w-0"><button className="font-medium text-left hover:underline" onClick={() => openReceipt(item.receipt_id)}>{item.vendor}</button><p className="muted">{item.receipt_date} · {item.category}{item.duplicate_receipt ? " · possible duplicate receipt" : ""}</p></div><div className="flex flex-wrap items-center gap-3"><span className="font-semibold tabular-nums">{amount(item.amount_cents / 100, currency)}</span><Status value={item.duplicate_receipt ? "DUPLICATE_RECEIPT" : item.status} /><PaymentDialog token={token} receipt={item} saved={() => setRefresh((value) => value + 1)} /><Button variant="ghost" onClick={() => openReceipt(item.receipt_id)}>Open <ArrowRight /></Button></div></div>)}</div>}
        </section>

        <section className="rounded-xl border border-sky-200 bg-sky-50 p-5 text-sky-950" aria-labelledby="compliance-title">
          <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 size-5 shrink-0" /><div><h2 id="compliance-title" className="font-semibold">Singapore record controls</h2><p className="mt-1 text-sm">Ledgerly keeps original receipt evidence, human decision history, payment follow-up events, and exportable monthly records. These controls support record keeping and PDPA accountability; they do not certify IRAS, GST, CPF, or PDPA compliance. Tax treatment and employee reimbursements still need your finance or HR reviewer.</p></div></div>
        </section>
      </>}
    </div>
  );
}

type StatementPreview = {
  statement_month: string; currency: string; account_label: string; imported_by: string;
  extraction_method: "deterministic" | "ai"; text_engine: string;
  metadata: { bank_name: string | null; account_last_four: string | null; opening_balance_cents: number | null; closing_balance_cents: number | null };
  validation: { balance_reconciled: boolean | null; confirmable: boolean; warnings: string[]; credits_skipped: number; outside_month: number };
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
            <Notice variant="info">PDFs are previewed before import. CSV files use the existing deterministic importer. Original files are retained only after import.</Notice>
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
  const [open, setOpen] = useState(false), [state, setState] = useState("TRADE_PAYABLE"), [actor, setActor] = useState(""), [note, setNote] = useState(""), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function submit(event: React.FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await request(`/receipts/${receipt.receipt_id}/payment-state`, token, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state, actor, note }) }); setOpen(false); saved(); } catch (e) { setError(message(e)); } finally { setBusy(false); } }
  return <Dialog open={open} onOpenChange={setOpen}><DialogTrigger asChild><Button variant="outline">Update status</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Record payment follow-up</DialogTitle><DialogDescription>This creates an audit event for {receipt.vendor}. It does not initiate or cancel a payment.</DialogDescription></DialogHeader><form onSubmit={submit} className="space-y-4"><div><label htmlFor="payment-state" className="field-label">Status</label><select id="payment-state" className="h-10 w-full rounded-md border bg-white px-3" value={state} onChange={(e) => setState(e.target.value)}><option value="TRADE_PAYABLE">Trade payable — valid amount still due</option><option value="PAYMENT_ISSUE">Payment issue — attempted or blocked</option><option value="CLEAR">Clear manual status</option></select></div><div><label htmlFor="payment-actor" className="field-label">Recorded by</label><Input id="payment-actor" required minLength={2} maxLength={100} value={actor} onChange={(e) => setActor(e.target.value)} /></div><div><label htmlFor="payment-note" className="field-label">Evidence and next step</label><Textarea id="payment-note" required minLength={5} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} placeholder="For example: bank transfer rejected; finance will confirm beneficiary details." /></div>{error && <Notice variant="destructive">{error}</Notice>}<DialogFooter><Button disabled={busy}>{busy && <LoaderCircle className="animate-spin" />}Save audit event</Button></DialogFooter></form></DialogContent></Dialog>;
}

function TotalCard({ icon, label, value, help, tone = "plain" }: { icon: React.ReactNode; label: string; value: string; help: string; tone?: "plain" | "good" | "warn" }) { const tones = { plain: "bg-slate-100 text-slate-700", good: "bg-emerald-50 text-emerald-700", warn: "bg-amber-50 text-amber-800" }; return <article className="panel p-5"><div className="flex items-start justify-between gap-3"><div><p className="field-label text-muted-foreground">{label}</p><p className="text-2xl font-semibold tabular-nums">{value}</p></div><span className={`rounded-xl p-2.5 [&>svg]:size-5 ${tones[tone]}`}>{icon}</span></div><p className="muted mt-2">{help}</p></article>; }
function Breakdown({ title, icon, items, currency }: { title: string; icon: React.ReactNode; items: { label: string; cents: number }[]; currency: string }) { const max = Math.max(1, ...items.map((item) => item.cents)); return <section className="panel p-5 sm:p-6"><div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-700">{icon}</span><h2 className="font-semibold">{title}</h2></div>{!items.length ? <p className="muted py-8 text-center">No accepted receipt spend for this period.</p> : <ol className="mt-5 space-y-4">{items.slice(0, 5).map((item, index) => <li key={item.label}><div className="mb-1.5 flex justify-between gap-3 text-sm"><span className="truncate"><span className="mr-2 text-muted-foreground">{index + 1}</span>{item.label}</span><strong className="shrink-0 tabular-nums">{amount(item.cents / 100, currency)}</strong></div><div className="h-2 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(3, item.cents / max * 100)}%` }} /></div></li>)}</ol>}</section>; }
function ExceptionTable({ title, empty, rows, currency }: { title: string; empty: string; rows: { id: string; primary: string; secondary: string; cents: number; status: string }[]; currency: string }) { return <section className="panel overflow-hidden"><div className="border-b p-5 sm:p-6"><h2 className="text-lg font-semibold">{title}</h2><p className="muted mt-1">Duplicates and missing receipt evidence stay visible for review.</p></div>{!rows.length ? <p className="muted p-8 text-center">{empty}</p> : <div className="divide-y">{rows.map((row) => <div key={row.id} className="flex flex-wrap items-center justify-between gap-4 p-4 sm:px-6"><div><p className="font-medium">{row.primary}</p><p className="muted">{row.secondary}</p></div><div className="flex items-center gap-3"><strong className="tabular-nums">{amount(row.cents / 100, currency)}</strong><Status value={row.status} /></div></div>)}</div>}</section>; }
function MonthlySkeleton() { return <div role="status" aria-label="Loading monthly close" className="space-y-5 animate-pulse"><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[0,1,2,3].map((item) => <div key={item} className="h-32 rounded-xl bg-muted" />)}</div><div className="h-48 rounded-xl bg-muted" /><span className="sr-only">Loading monthly close…</span></div>; }
