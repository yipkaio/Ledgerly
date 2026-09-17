import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { amount } from "@/lib/api";
import type { Extraction } from "@/lib/api";

function Value({ children }: { children: React.ReactNode }) {
  return <dd className="mt-1 text-sm font-medium break-words">{children || "—"}</dd>;
}

function Datum({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-lg bg-muted/70 px-3.5 py-3">
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {label}
      </dt>
      <Value>{children}</Value>
    </div>
  );
}

export function ReceiptSummary({
  data,
  category,
}: {
  data: Extraction;
  category: string;
}) {
  const currency = data.currency;
  return (
    <section className="panel overflow-hidden" aria-labelledby="receipt-data-title">
      <div className="border-b bg-gradient-to-r from-emerald-50/80 to-white p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-[0.14em] text-primary uppercase">
              Effective receipt record
            </p>
            <h2 id="receipt-data-title" className="mt-1 truncate text-xl font-semibold">
              {data.vendor || "Vendor unavailable"}
            </h2>
            <p className="muted mt-1">
              {data.receipt_number || "No receipt number"} · {data.date || "No date"}
            </p>
          </div>
          <div className="text-left sm:text-right">
            <p className="text-2xl font-semibold tabular-nums">
              {amount(data.total_amount, currency)}
            </p>
            {category && <Badge className="mt-2" variant="secondary">{category}</Badge>}
          </div>
        </div>
      </div>

      <div className="space-y-7 p-5 sm:p-6">
        <section aria-labelledby="merchant-details-title">
          <h3 id="merchant-details-title" className="font-semibold">Merchant details</h3>
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            <Datum label="Legal entity">{data.legal_entity}</Datum>
            <Datum label="Registration number">{data.company_registration_number}</Datum>
            <Datum label="Branch">{data.branch}</Datum>
            <Datum label="Payment method">{data.payment_method}</Datum>
          </dl>
        </section>

        <section aria-labelledby="line-items-title">
          <div className="flex items-end justify-between gap-3">
            <h3 id="line-items-title" className="font-semibold">Line items</h3>
            <p className="muted">{data.line_items.length} item{data.line_items.length === 1 ? "" : "s"}</p>
          </div>
          <div className="mt-3 overflow-x-auto rounded-xl border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Unit price</TableHead>
                  <TableHead className="text-right">Discount</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.line_items.map((item, index) => {
                  const discount = item.discount_amount != null
                    ? amount(item.discount_amount, currency)
                    : item.discount_percent != null
                      ? `${item.discount_percent}%`
                      : "—";
                  return (
                    <TableRow key={`${item.description || "item"}-${index}`}>
                      <TableCell className="min-w-56 font-medium">
                        {item.description || `Item ${index + 1}`}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{item.quantity ?? "—"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap tabular-nums">
                        {amount(item.unit_price, currency)}
                      </TableCell>
                      <TableCell className="text-right whitespace-nowrap tabular-nums">{discount}</TableCell>
                      <TableCell className="text-right whitespace-nowrap font-medium tabular-nums">
                        {amount(item.line_total, currency)}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!data.line_items.length && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      No line items were extracted.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </section>

        <section aria-labelledby="totals-title" className="grid gap-5 lg:grid-cols-[1fr_18rem]">
          <div>
            <h3 id="totals-title" className="font-semibold">Payment details</h3>
            <dl className="mt-3 grid gap-3 sm:grid-cols-2">
              <Datum label="Cash tendered">{amount(data.cash_tendered, currency)}</Datum>
              <Datum label="Change">{amount(data.change_amount, currency)}</Datum>
            </dl>
          </div>
          <dl className="rounded-xl border bg-muted/40 p-4 text-sm">
            {[
              ["Subtotal", data.subtotal],
              ["Tax", data.tax_amount],
              ["Before rounding", data.total_before_rounding],
              ["Rounding", data.rounding_adjustment],
            ].map(([label, value]) => (
              <div key={String(label)} className="flex justify-between gap-4 py-1.5">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-medium tabular-nums">{amount(value as number | null, currency)}</dd>
              </div>
            ))}
            <div className="mt-2 flex justify-between gap-4 border-t pt-3 text-base">
              <dt className="font-semibold">Total</dt>
              <dd className="font-semibold tabular-nums">{amount(data.total_amount, currency)}</dd>
            </div>
          </dl>
        </section>
      </div>
    </section>
  );
}
