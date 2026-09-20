import { useClock } from "@/lib/use-clock";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  FileCheck2,
  Upload,
  ListChecks,
  History,
  Trash2,
  LogOut,
  ArrowLeft,
  ArrowRight,
  LoaderCircle,
  LayoutDashboard,
  Landmark,
  Download,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  amount,
  ApiError,
  categories,
  message,
  request,
  requestDownload,
  rowStatus,
} from "@/lib/api";
import type { Page } from "@/lib/api";
import { Notice, Status } from "@/components/feedback";
import {
  ReceiptPreview,
  ReceiptPreviewProvider,
} from "@/components/receipt-preview";
const Dashboard = lazy(() =>
  import("@/components/dashboard").then((m) => ({ default: m.Dashboard })),
);
const ReceiptDetail = lazy(() =>
  import("@/components/receipt-detail").then((m) => ({
    default: m.ReceiptDetail,
  })),
);
const MonthlyClose = lazy(() =>
  import("@/components/monthly-close").then((m) => ({ default: m.MonthlyClose })),
);

type HistoryFilterValues = {
  query: string;
  category: string[];
  currency: string[];
  state: string[];
  date_from: string;
  date_to: string;
};
const emptyFilters: HistoryFilterValues = {
  query: "",
  category: [],
  currency: [],
  state: [],
  date_from: "",
  date_to: "",
};
const historyStatuses = [
  "AUTO_FILED",
  "APPROVED",
  "AMENDED",
  "VOIDED",
  "REJECTED",
  "REVIEW_QUEUE",
  "PROCESSING",
  "FAILED",
];
const historyCurrencies = ["SGD", "MYR", "USD", "EUR", "GBP", "AUD"];

function filterParams(filters: HistoryFilterValues) {
  return {
    ...(filters.query.trim() ? { query: filters.query.trim() } : {}),
    ...(filters.category.length ? { category: filters.category } : {}),
    ...(filters.currency.length ? { currency: filters.currency } : {}),
    ...(filters.state.length ? { state: filters.state } : {}),
    ...(filters.date_from ? { date_from: filters.date_from } : {}),
    ...(filters.date_to ? { date_to: filters.date_to } : {}),
  };
}

export default function App() {
  const [token, setToken] = useState(""),
    [draft, setDraft] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await request<Page>("/receipts?limit=1", draft.trim());
      setToken(draft.trim());
      setDraft("");
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  if (token)
    return (
      <Workspace
        token={token}
        disconnect={() => {
          setToken("");
          setDraft("");
          setError("");
        }}
      />
    );
  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center px-5 py-12">
      <div className="w-full">
        <div className="mb-8 flex items-center gap-3">
          <FileCheck2 className="size-9 text-primary" />
          <span className="text-xl font-semibold">Ledgerly</span>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">
          Your receipt workspace
        </h1>
        <p className="muted mt-3 mb-8">
          Upload expenses, check the evidence, and keep a clear record of every
          decision.
        </p>
        <form onSubmit={connect} className="panel space-y-5 p-6">
          <div>
            <label htmlFor="app-key" className="field-label">
              App API key
            </label>
            <Input
              id="app-key"
              type="password"
              autoComplete="off"
              required
              minLength={32}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <p className="muted mt-2">
              Use this server’s APP_API_KEY. The key stays in memory until you
              disconnect or reload. Use only on a trusted device.
            </p>
          </div>
          {error && <Notice variant="destructive">{error}</Notice>}
          <Button className="w-full" disabled={busy}>
            {busy && <LoaderCircle className="animate-spin" />}Connect to
            workspace
          </Button>
        </form>
        <p className="muted mt-5">
          Shared workspace access · Reviewer names are self reported.
        </p>
      </div>
    </main>
  );
}
function Workspace({
  token,
  disconnect,
}: {
  token: string;
  disconnect: () => void;
}) {
  const [view, setView] = useState<
      "dashboard" | "monthly" | "history" | "reviews" | "upload" | "deleted"
    >("dashboard"),
    [selected, setSelected] = useState<string | null>(null),
    [offset, setOffset] = useState(0),
    [page, setPage] = useState<Page | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [refresh, setRefresh] = useState(0),
    [dirty, setDirty] = useState(false),
    [filterDraft, setFilterDraft] = useState(emptyFilters),
    [filters, setFilters] = useState(emptyFilters),
    [checked, setChecked] = useState<Set<string>>(new Set()),
    [exportBusy, setExportBusy] = useState(false);
  const now = useClock();
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (view === "upload" || view === "dashboard" || view === "monthly" || selected) return;
    const controller = new AbortController();
    // oxlint-disable-next-line react/set-state-in-effect -- Reset status for this cancellable API read.
    setBusy(true);
    setError("");
    setPage(null);
    const params = new URLSearchParams({ limit: "20", offset: String(offset) });
    if (view === "deleted") params.set("state", "DELETED");
    if (view === "history") {
      for (const [key, value] of Object.entries(filterParams(filters)))
        params.set(key, value);
    }
    request<Page>(
      `${view === "reviews" ? "/reviews" : "/receipts"}?${params}`,
      token,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setPage(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [token, view, offset, selected, refresh, filters]);
  useEffect(() => {
    heading.current?.focus();
  }, [view, selected]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function discardChanges() {
    if (dirty && !window.confirm("Discard unsaved review changes?"))
      return false;
    setDirty(false);
    return true;
  }
  function navigate(next: typeof view) {
    if (!discardChanges()) return;
    setSelected(null);
    setView(next);
    setChecked(new Set());
    setOffset(0);
  }
  async function exportExcel(allFiltered: boolean) {
    if (!allFiltered && checked.size === 0) return;
    setExportBusy(true);
    setError("");
    try {
      const body = allFiltered
        ? { filters: filterParams(filters) }
        : { receipt_ids: [...checked] };
      const result = await requestDownload("/receipts/export", token, body);
      const url = URL.createObjectURL(result.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = result.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(message(e));
    } finally {
      setExportBusy(false);
    }
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="border-b bg-white">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-8">
          <a
            href="/ui/"
            onClick={(event) => {
              event.preventDefault();
              navigate("dashboard");
            }}
            className="flex items-center gap-2 text-lg font-semibold"
          >
            <FileCheck2 className="size-7 text-primary" />
            Ledgerly
          </a>
          <div className="flex items-center gap-3">
            <span className="muted hidden sm:inline">Receipt workspace</span>
            <Button
              variant="ghost"
              onClick={() => {
                if (discardChanges()) disconnect();
              }}
            >
              <LogOut />
              Disconnect
            </Button>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-8">
        <nav aria-label="Workspace" className="mb-7 flex flex-wrap gap-2">
          {(
            [
              ["dashboard", LayoutDashboard, "Main dashboard"],
              ["monthly", Landmark, "Monthly close"],
              ["upload", Upload, "Upload receipt"],
              ["reviews", ListChecks, "Pending reviews"],
              ["history", History, "Receipt history"],
              ["deleted", Trash2, "Deleted receipts"],
            ] as const
          ).map(([id, Icon, label]) => (
            <Button
              key={id}
              variant={view === id ? "default" : "outline"}
              aria-current={view === id ? "page" : undefined}
              onClick={() => navigate(id)}
            >
              <Icon />
              {label}
            </Button>
          ))}
        </nav>
        <main id="main">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="muted mb-1">EXPENSE OPERATIONS</p>
              <h1
                ref={heading}
                tabIndex={-1}
                className="text-3xl font-semibold tracking-tight"
              >
                {selected
                  ? view === "reviews"
                    ? "Review receipt"
                    : "Receipt details"
                  : view === "dashboard"
                    ? "Main dashboard"
                    : view === "monthly"
                      ? "Monthly close"
                    : view === "upload"
                      ? "Upload receipt"
                      : view === "reviews"
                        ? "Pending reviews"
                        : view === "deleted"
                          ? "Deleted receipts"
                          : "Receipt history"}
              </h1>
            </div>
            {selected && (
              <Button
                variant="outline"
                onClick={() => {
                  if (discardChanges()) setSelected(null);
                }}
              >
                <ArrowLeft />
                Back to list
              </Button>
            )}
          </div>
          {selected ? (
            <Suspense fallback={<p role="status">Loading review tools…</p>}>
              <ReceiptDetail
                key={selected}
                id={selected}
                token={token}
                context={view === "reviews" ? "review" : "history"}
                onDirty={setDirty}
                dirty={dirty}
                saved={() => {
                  setRefresh((n) => n + 1);
                  if (view === "reviews") setOffset(0);
                }}
              />
            </Suspense>
          ) : view === "dashboard" ? (
            <Suspense fallback={<p role="status">Loading dashboard…</p>}>
              <Dashboard token={token} navigate={navigate} />
            </Suspense>
          ) : view === "monthly" ? (
            <Suspense fallback={<p role="status">Loading monthly close…</p>}>
              <MonthlyClose token={token} openReceipt={(id) => { setView("history"); setSelected(id); }} />
            </Suspense>
          ) : view === "upload" ? (
            <UploadForm
              token={token}
              open={(id) => {
                setView("history");
                setOffset(0);
                setSelected(id);
              }}
            />
          ) : (
            <>
              <p className="muted mb-5">
                {view === "reviews"
                  ? "Check the original receipt and business purpose before making a final decision."
                  : view === "deleted"
                    ? "Restore receipts within 30 days. Expired receipts and their files are automatically erased; finalized receipts never enter this area."
                    : "Human decisions take precedence. Voided receipts remain visible as evidence and are excluded from totals and exports."}
              </p>
              {view === "history" && (
                <form
                  className="panel mb-5 grid gap-4 p-4 md:grid-cols-3 xl:grid-cols-6"
                  aria-label="Receipt history filters"
                  onSubmit={(event) => {
                    event.preventDefault();
                    setFilters({ ...filterDraft });
                    setOffset(0);
                    setChecked(new Set());
                  }}
                >
                  <div className="md:col-span-2">
                    <label htmlFor="history-search" className="field-label">
                      Vendor, receipt number or ID
                    </label>
                    <Input
                      id="history-search"
                      maxLength={100}
                      value={filterDraft.query}
                      onChange={(event) =>
                        setFilterDraft((old) => ({
                          ...old,
                          query: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="history-category">
                      Category
                    </label>
                    <Select
                      value={filterDraft.category || "all"}
                      onValueChange={(value) =>
                        setFilterDraft((old) => ({
                          ...old,
                          category: value === "all" ? "" : value,
                        }))
                      }
                    >
                      <SelectTrigger id="history-category">
                        <SelectValue placeholder="All categories" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All categories</SelectItem>
                        {categories.map((value) => (
                          <SelectItem value={value} key={value}>
                            {value}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="history-state">
                      Status
                    </label>
                    <Select
                      value={filterDraft.state || "all"}
                      onValueChange={(value) =>
                        setFilterDraft((old) => ({
                          ...old,
                          state: value === "all" ? "" : value,
                        }))
                      }
                    >
                      <SelectTrigger id="history-state">
                        <SelectValue placeholder="All statuses" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All statuses</SelectItem>
                        {[
                          "AUTO_FILED",
                          "APPROVED",
                          "AMENDED",
                          "VOIDED",
                          "REJECTED",
                          "REVIEW_QUEUE",
                          "PROCESSING",
                          "FAILED",
                        ].map((value) => (
                          <SelectItem value={value} key={value}>
                            {value.replaceAll("_", " ")}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="history-currency">
                      Currency
                    </label>
                    <Input
                      id="history-currency"
                      maxLength={3}
                      placeholder="MYR"
                      value={filterDraft.currency}
                      onChange={(event) =>
                        setFilterDraft((old) => ({
                          ...old,
                          currency: event.target.value.toUpperCase(),
                        }))
                      }
                    />
                  </div>
                  <div className="flex items-end gap-2">
                    <Button type="submit">Apply filters</Button>
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label="Clear history filters"
                      onClick={() => {
                        setFilterDraft(emptyFilters);
                        setFilters(emptyFilters);
                        setOffset(0);
                        setChecked(new Set());
                      }}
                    >
                      <X />
                    </Button>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="history-date-from">
                      Receipt date from
                    </label>
                    <Input
                      id="history-date-from"
                      type="date"
                      value={filterDraft.date_from}
                      onChange={(event) =>
                        setFilterDraft((old) => ({
                          ...old,
                          date_from: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div>
                    <label className="field-label" htmlFor="history-date-to">
                      Receipt date to
                    </label>
                    <Input
                      id="history-date-to"
                      type="date"
                      value={filterDraft.date_to}
                      onChange={(event) =>
                        setFilterDraft((old) => ({
                          ...old,
                          date_to: event.target.value,
                        }))
                      }
                    />
                  </div>
                </form>
              )}
              {busy && (
                <p role="status" className="muted py-8">
                  Loading receipts…
                </p>
              )}
              {error && (
                <Notice variant="destructive">
                  {error}{" "}
                  <Button
                    variant="outline"
                    onClick={() => setRefresh((n) => n + 1)}
                  >
                    Try again
                  </Button>
                </Notice>
              )}
              {page && (
                <div className="panel overflow-hidden">
                  {view === "history" && (
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
                      <p className="muted" aria-live="polite">
                        {checked.size} selected across pages · Voided receipts
                        excluded
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          disabled={!checked.size || exportBusy}
                          onClick={() => void exportExcel(false)}
                        >
                          <Download /> Export selected
                        </Button>
                        <Button
                          variant="outline"
                          disabled={!page.total || exportBusy}
                          onClick={() => void exportExcel(true)}
                        >
                          <Download /> Export filtered
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={!checked.size || exportBusy}
                          onClick={() => setChecked(new Set())}
                        >
                          Clear selection
                        </Button>
                      </div>
                    </div>
                  )}
                  <ReceiptPreviewProvider>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          {view === "history" && (
                            <TableHead className="w-12">
                              <input
                                type="checkbox"
                                aria-label="Select all receipts on this page"
                                checked={
                                  !!page.items.filter(
                                    (row) => rowStatus(row) !== "VOIDED",
                                  ).length &&
                                  page.items
                                    .filter(
                                      (row) => rowStatus(row) !== "VOIDED",
                                    )
                                    .every((row) => checked.has(row.receipt_id))
                                }
                                onChange={(event) => {
                                  setChecked((old) => {
                                    const next = new Set(old);
                                    for (const row of page.items) {
                                      if (
                                        event.target.checked &&
                                        rowStatus(row) !== "VOIDED"
                                      )
                                        next.add(row.receipt_id);
                                      else next.delete(row.receipt_id);
                                    }
                                    return next;
                                  });
                                }}
                              />
                            </TableHead>
                          )}
                          <TableHead>Vendor / receipt</TableHead>
                          <TableHead>
                            {view === "deleted"
                              ? "Restore deadline"
                              : "Uploaded"}
                          </TableHead>
                          <TableHead>Amount</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>
                            <span className="sr-only">Actions</span>
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {page.items.map((row) => (
                          <TableRow key={row.receipt_id}>
                            {view === "history" && (
                              <TableCell>
                                <input
                                  type="checkbox"
                                  aria-label={`Select receipt ${row.vendor || row.receipt_id}`}
                                  disabled={rowStatus(row) === "VOIDED"}
                                  checked={checked.has(row.receipt_id)}
                                  onChange={(event) =>
                                    setChecked((old) => {
                                      const next = new Set(old);
                                      if (event.target.checked)
                                        next.add(row.receipt_id);
                                      else next.delete(row.receipt_id);
                                      return next;
                                    })
                                  }
                                />
                              </TableCell>
                            )}
                            <TableCell>
                              <p className="font-medium">
                                {row.vendor || "Vendor unavailable"}
                              </p>
                              <p className="muted font-mono text-xs">
                                {row.receipt_id.slice(0, 8)}
                              </p>
                            </TableCell>
                            <TableCell>
                              {view === "deleted" && row.purge_after ? (
                                <span className="text-sm">
                                  <time dateTime={row.purge_after}>
                                    {new Date(row.purge_after).toLocaleString()}
                                  </time>
                                  <span className="muted block">
                                    {new Date(row.purge_after).getTime() <= now
                                      ? "Awaiting permanent erasure"
                                      : `${Math.ceil((new Date(row.purge_after).getTime() - now) / 86400000)} days remaining`}
                                  </span>
                                </span>
                              ) : (
                                new Date(row.created_at).toLocaleDateString()
                              )}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">
                              {amount(row.total_amount, row.currency)}
                            </TableCell>
                            <TableCell>
                              <Status value={rowStatus(row)} />
                            </TableCell>
                            <TableCell>
                              <div className="flex items-center justify-end gap-1">
                                <ReceiptPreview
                                  row={row}
                                  token={token}
                                  onOpen={() => setSelected(row.receipt_id)}
                                />
                                <Button
                                  variant="outline"
                                  onClick={() => setSelected(row.receipt_id)}
                                  aria-label={`${view === "reviews" ? "Review" : "Open"} receipt ${row.vendor || row.receipt_id}`}
                                >
                                  {view === "reviews" ? "Review" : "Open"}
                                  <ArrowRight />
                                </Button>
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                        {!page.items.length && (
                          <TableRow>
                            <TableCell
                              colSpan={view === "history" ? 6 : 5}
                              className="py-12 text-center text-muted-foreground"
                            >
                              {view === "reviews"
                                ? "No receipts are waiting for review."
                                : view === "deleted"
                                  ? "No deleted receipts. Your workspace is tidy."
                                  : "No receipts match this view. Try clearing your filters or upload a receipt."}
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                  </ReceiptPreviewProvider>
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3">
                    <p className="muted">
                      {page.total
                        ? `${offset + 1}–${Math.min(offset + 20, page.total)} of ${page.total}`
                        : "0 receipts"}
                    </p>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        disabled={offset === 0 || busy}
                        onClick={() => setOffset((n) => Math.max(0, n - 20))}
                      >
                        Previous
                      </Button>
                      <Button
                        variant="outline"
                        disabled={offset + 20 >= page.total || busy}
                        onClick={() => setOffset((n) => n + 20)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </main>
        <footer className="muted mt-10 border-t pt-4">
          Evidence first. Every human decision keeps the original extraction and
          an audit record.
        </footer>
      </div>
    </>
  );
}
function UploadForm({
  token,
  open,
}: {
  token: string;
  open: (id: string) => void;
}) {
  const [file, setFile] = useState<File | null>(null),
    [purpose, setPurpose] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [failedId, setFailedId] = useState<string | null>(null);
  const active = useRef(true),
    submitting = useRef(false);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting.current) return;
    setError("");
    setFailedId(null);
    if (
      !file ||
      !["image/jpeg", "image/png", "application/pdf"].includes(file.type) ||
      file.size > 5242880
    ) {
      setError("Choose a JPEG, PNG, or PDF receipt up to 5 MB.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    const body = new FormData();
    body.set("receipt", file);
    if (purpose.trim()) body.set("business_purpose", purpose.trim());
    try {
      const result = await request<{ receipt_id: string }>(
        "/receipts/upload",
        token,
        { method: "POST", body, timeoutMs: 330000 },
      );
      if (active.current) open(result.receipt_id);
    } catch (err) {
      if (!active.current) return;
      setError(
        message(err) +
          " Check history before uploading again; processing may already have started.",
      );
      if (err instanceof ApiError) setFailedId(err.receiptId);
    } finally {
      submitting.current = false;
      if (active.current) setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="panel max-w-2xl space-y-6 p-6">
      <div className="rounded-lg border border-dashed bg-muted p-6">
        <Upload className="mb-3 size-7 text-primary" />
        <label htmlFor="receipt-file" className="field-label">
          Receipt file
        </label>
        <Input
          id="receipt-file"
          type="file"
          accept="image/jpeg,image/png,application/pdf,.pdf"
          required
          disabled={busy}
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <p className="muted mt-2">
          JPEG, PNG, or PDF · Up to 5 MB · PDF up to 3 pages · One receipt per
          upload
        </p>
      </div>
      <div>
        <label htmlFor="purpose" className="field-label">
          Business purpose (optional)
        </label>
        <Textarea
          id="purpose"
          maxLength={500}
          value={purpose}
          disabled={busy}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="For example: cleaning supplies for the office"
        />
        <p className="muted mt-2">
          Explain how the purchase is used. Missing purpose may require human
          review.
        </p>
      </div>
      {error && (
        <Notice variant="destructive">
          {error}
          {failedId && (
            <Button variant="outline" onClick={() => open(failedId)}>
              View saved processing record
            </Button>
          )}
        </Notice>
      )}
      <Button disabled={busy || !file}>
        {busy ? <LoaderCircle className="animate-spin" /> : <Upload />}
        {busy ? "Processing receipt…" : "Upload and process"}
      </Button>
      <p className="muted">
        OCR runs on the server. Extraction and classification may use gateway
        credits. Keep this page open while processing.
      </p>
    </form>
  );
}
