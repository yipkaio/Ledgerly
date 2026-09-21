import { useState } from "react";
import { amount } from "@/lib/api";
import { monthNames, periodLabel, periodTotals, type MonthTotal, type PeriodMode } from "@/lib/dashboard-periods";

const colors = ["#047857", "#2563eb", "#9333ea", "#c2410c", "#be185d", "#0e7490"];

export function TrendChart({ currency, items }: { currency: string; items: MonthTotal[] }) {
  const [mode, setMode] = useState<PeriodMode>("month");
  const [years, setYears] = useState<string[] | null>(null);
  const [parts, setParts] = useState<number[] | null>(null);
  const [active, setActive] = useState("");
  const availableYears = Array.from(new Set(items.map((item) => item.month.slice(0, 4)))).sort();
  const selectedYears = (years ?? availableYears.slice(-2)).filter((year) => availableYears.includes(year));
  const labels = mode === "quarter" ? ["Q1", "Q2", "Q3", "Q4"] : monthNames;
  const selectedParts = mode === "year" ? [1] : parts ?? labels.map((_, index) => index + 1);
  const rows = selectedYears.flatMap((year) => selectedParts.map((part) => ({
    key: `${year}-${part}`, year, part, label: periodLabel(mode, year, part),
    ...periodTotals(items, mode, year, part),
  })));
  const selected = rows.find((row) => row.key === active) || rows.at(-1);
  const max = Math.max(1, ...rows.map((row) => row.total_cents));
  const min = Math.min(0, ...rows.map((row) => row.total_cents));
  const y = (value: number) => 215 - ((value - min) / (max - min)) * 180;
  const x = (index: number, count: number) => count === 1 ? 340 : 90 + index * 500 / (count - 1);
  const baseline = rows[0];
  const delta = selected && baseline ? selected.total_cents - baseline.total_cents : 0;
  function toggleYear(year: string) {
    setYears(selectedYears.includes(year) ? selectedYears.filter((value) => value !== year) : [...selectedYears, year].sort());
  }
  function togglePart(part: number) {
    setParts(selectedParts.includes(part) ? selectedParts.filter((value) => value !== part) : [...selectedParts, part].sort((a, b) => a - b));
  }
  return <section className="panel min-w-0 overflow-hidden p-5 sm:p-6" aria-labelledby="trend-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="trend-title" className="text-lg font-semibold">Expense trend & comparison</h2>
      <select aria-label="Trend comparison period" className="rounded-lg border bg-white p-2 text-sm" value={mode}
        onChange={(event) => { setMode(event.target.value as PeriodMode); setParts(null); setActive(""); }}>
        <option value="month">Compare months</option><option value="quarter">Compare quarters</option><option value="year">Compare years</option>
      </select>
    </div>
    {!items.length ? <p className="muted py-12 text-center">No dated accepted receipts yet.</p> : <>
      <fieldset className="mt-4"><legend className="mb-2 text-xs font-semibold uppercase text-muted-foreground">Years · select multiple</legend>
        <div className="flex flex-wrap gap-2">{availableYears.map((year, index) => <label key={year}
          className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${selectedYears.includes(year) ? "border-emerald-300 bg-emerald-50" : ""}`}>
          <input type="checkbox" checked={selectedYears.includes(year)} onChange={() => toggleYear(year)} />
          <span className="size-2 rounded-full" style={{ backgroundColor: colors[index % colors.length] }} />{year}
        </label>)}</div>
      </fieldset>
      {mode !== "year" && <fieldset className="mt-4"><legend className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{mode === "month" ? "Months" : "Quarters"} · select multiple</legend>
        <div className="flex flex-wrap gap-2">{labels.map((label, index) => <label key={label} className="flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs">
          <input type="checkbox" checked={selectedParts.includes(index + 1)} onChange={() => togglePart(index + 1)} />{label}
        </label>)}</div>
      </fieldset>}
      {!rows.length ? <p className="muted py-10 text-center">Select at least one year and period to compare.</p> : <>
        <div className="mt-5 rounded-xl bg-emerald-50 p-4" aria-live="polite">
          <div className="text-xs font-medium text-emerald-800">{selected?.label} · {selected?.receipt_count} receipts</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{amount((selected?.total_cents || 0) / 100, currency)}</div>
          {selected && baseline && selected.key !== baseline.key && <p className="mt-1 text-xs text-muted-foreground">
            {delta > 0 ? "+" : ""}{amount(delta / 100, currency)} vs {baseline.label}
            {baseline.total_cents !== 0 ? ` (${((delta / Math.abs(baseline.total_cents)) * 100).toFixed(1)}%)` : " · percentage unavailable from zero"}
          </p>}
        </div>
        <p className="mt-3 text-xs text-muted-foreground">Hover, tap or focus a point to inspect. Missing periods show zero recorded spend.</p>
        <div className="overflow-x-auto">
          <svg viewBox="0 0 640 265" className="mt-2 w-full min-w-[480px]" role="img" aria-label={`Accepted spend comparison in ${currency}; exact values below`}>
            {[0, 1, 2, 3, 4].map((tick) => {
              const value = min + (max - min) * tick / 4;
              return <g key={tick}><line x1="85" x2="605" y1={y(value)} y2={y(value)} stroke="#e2e8f0" strokeDasharray="4 4" />
                <text x="78" y={y(value) + 4} textAnchor="end" fontSize="10" fill="#64748b">{(value / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}</text></g>;
            })}
            {mode === "year" ? <>
              <polyline fill="none" stroke="#047857" strokeWidth="3" points={rows.map((row, index) => `${x(index, rows.length)},${y(row.total_cents)}`).join(" ")} />
              {rows.map((row, index) => <g key={row.key}>
                <circle cx={x(index, rows.length)} cy={y(row.total_cents)} r={active === row.key ? 8 : 6} fill="#047857" tabIndex={0} role="button"
                  aria-label={`${row.label}: ${amount(row.total_cents / 100, currency)}`}
                  onMouseEnter={() => setActive(row.key)} onFocus={() => setActive(row.key)} onClick={() => setActive(row.key)}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(row.key); } }}>
                  <title>{row.label}: {amount(row.total_cents / 100, currency)}</title>
                </circle><text x={x(index, rows.length)} y="245" textAnchor="middle" fontSize="11">{row.year}</text>
              </g>)}
            </> : selectedYears.map((year) => {
              const series = rows.filter((row) => row.year === year);
              const color = colors[availableYears.indexOf(year) % colors.length];
              return <g key={year}>
                <polygon fill={color} opacity="0.04" points={`${x(0, series.length)},${y(0)} ${series.map((row, index) => `${x(index, series.length)},${y(row.total_cents)}`).join(" ")} ${x(series.length - 1, series.length)},${y(0)}`} />
                <polyline fill="none" stroke={color} strokeWidth="3" points={series.map((row, index) => `${x(index, series.length)},${y(row.total_cents)}`).join(" ")} />
                {series.map((row, index) => <circle key={row.key} cx={x(index, series.length)} cy={y(row.total_cents)} r={active === row.key ? 8 : 5}
                  fill={color} stroke="white" strokeWidth="2" tabIndex={0} role="button" aria-label={`${row.label}: ${amount(row.total_cents / 100, currency)}`}
                  onMouseEnter={() => setActive(row.key)} onFocus={() => setActive(row.key)} onClick={() => setActive(row.key)}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setActive(row.key); } }}>
                  <title>{row.label}: {amount(row.total_cents / 100, currency)}</title>
                </circle>)}
              </g>;
            })}
            {mode !== "year" && selectedParts.map((part, index) => <text key={part} x={x(index, selectedParts.length)} y="245" textAnchor="middle" fontSize="11" fill="#64748b">{labels[part - 1]}</text>)}
          </svg>
        </div>
        <details className="mt-2 rounded-lg border p-3" open={rows.length <= 4}>
          <summary className="cursor-pointer text-sm font-medium">Exact comparison values · {rows.length} periods</summary>
          <div className="mt-3 max-h-64 overflow-auto"><table className="w-full text-sm">
            <thead><tr className="border-b text-left"><th className="py-2">Period</th><th className="text-right">Spend ({currency})</th><th className="text-right">Receipts</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.key} className="border-b"><td className="py-2"><button className="hover:underline" onClick={() => setActive(row.key)}>{row.label}</button></td>
              <td className="text-right tabular-nums">{amount(row.total_cents / 100, currency)}</td><td className="text-right">{row.receipt_count}</td></tr>)}</tbody>
          </table></div>
        </details>
      </>}
    </>}
  </section>;
}
