import { useState } from "react";
import { amount } from "@/lib/api";
import { trendSeries, type DateRange, type MonthTotal } from "@/lib/dashboard-periods";

export function TrendChart({
  currency,
  items,
  range,
  rangeLabel,
}: {
  currency: string;
  items: MonthTotal[];
  range: DateRange;
  rangeLabel: string;
}) {
  const [active, setActive] = useState("");
  const rows = trendSeries(items, range);
  const selected = rows.find((row) => row.month === active) || rows.at(-1);
  const baseline = rows[0];
  const max = Math.max(1, ...rows.map((row) => row.total_cents));
  const y = (value: number) => 215 - (value / max) * 180;
  const x = (index: number) => rows.length === 1 ? 340 : 90 + index * 500 / (rows.length - 1);
  const labelInterval = Math.max(1, Math.ceil(rows.length / 10));
  const delta = selected && baseline ? selected.total_cents - baseline.total_cents : 0;
  const resolution = rows.some((row) => row.month.length === 4) ? "Yearly" : "Monthly";

  return <section className="panel min-w-0 overflow-hidden p-5 sm:p-6" aria-labelledby="trend-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 id="trend-title" className="text-lg font-semibold">Accepted expense trend</h2>
        <p className="muted mt-1">{rangeLabel}</p>
      </div>
      <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">
        {resolution} view
      </span>
    </div>
    {!rows.length ? <p className="muted py-12 text-center">No dated accepted receipts in this range.</p> : <>
      <div className="mt-5 rounded-xl bg-emerald-50 p-4" aria-live="polite">
        <div className="text-xs font-medium text-emerald-800">{selected?.label} · {selected?.receipt_count} receipts</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">{amount((selected?.total_cents || 0) / 100, currency)}</div>
        {selected && baseline && selected.month !== baseline.month && <p className="mt-1 text-xs text-muted-foreground">
          {delta > 0 ? "+" : ""}{amount(delta / 100, currency)} vs {baseline.label}
          {baseline.total_cents !== 0 ? ` (${((delta / Math.abs(baseline.total_cents)) * 100).toFixed(1)}%)` : " · percentage unavailable from zero"}
        </p>}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">Hover, tap or focus a point to inspect it. Missing months show zero recorded spend.</p>
      <div className="overflow-x-auto">
        <svg viewBox="0 0 640 265" className="mt-2 w-full min-w-[480px]" role="img" aria-label={`Accepted spend trend in ${currency}; exact values below`}>
          {[0, 1, 2, 3, 4].map((tick) => {
            const value = max * tick / 4;
            return <g key={tick}><line x1="85" x2="605" y1={y(value)} y2={y(value)} stroke="#e2e8f0" strokeDasharray="4 4" />
              <text x="78" y={y(value) + 4} textAnchor="end" fontSize="10" fill="#64748b">{(value / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}</text></g>;
          })}
          {rows.length > 1 && <polygon fill="#047857" opacity="0.06" points={`${x(0)},${y(0)} ${rows.map((row, index) => `${x(index)},${y(row.total_cents)}`).join(" ")} ${x(rows.length - 1)},${y(0)}`} />}
          <polyline fill="none" stroke="#047857" strokeWidth="3" points={rows.map((row, index) => `${x(index)},${y(row.total_cents)}`).join(" ")} />
          {rows.map((row, index) => <g key={row.month}>
            <circle cx={x(index)} cy={y(row.total_cents)} r={selected?.month === row.month ? 7 : 5}
              fill="#047857" stroke="white" strokeWidth="2" tabIndex={0} role="button"
              aria-label={`${row.label}: ${amount(row.total_cents / 100, currency)}`}
              onMouseEnter={() => setActive(row.month)} onFocus={() => setActive(row.month)} onClick={() => setActive(row.month)}
              onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(row.month); } }}>
              <title>{row.label}: {amount(row.total_cents / 100, currency)}</title>
            </circle>
            {(index % labelInterval === 0 || index === rows.length - 1) && <text x={x(index)} y="245" textAnchor="middle" fontSize="10" fill="#64748b">{row.label}</text>}
          </g>)}
        </svg>
      </div>
      <details className="mt-2 rounded-lg border p-3" open={rows.length <= 6}>
        <summary className="cursor-pointer text-sm font-medium">Exact values · {rows.length} periods</summary>
        <div className="mt-3 max-h-64 overflow-auto"><table className="w-full text-sm">
          <thead><tr className="border-b text-left"><th className="py-2">Period</th><th className="text-right">Spend ({currency})</th><th className="text-right">Receipts</th></tr></thead>
          <tbody>{rows.map((row) => <tr key={row.month} className="border-b"><td className="py-2"><button className="hover:underline" onClick={() => setActive(row.month)}>{row.label}</button></td>
            <td className="text-right tabular-nums">{amount(row.total_cents / 100, currency)}</td><td className="text-right">{row.receipt_count}</td></tr>)}</tbody>
        </table></div>
      </details>
    </>}
  </section>;
}
