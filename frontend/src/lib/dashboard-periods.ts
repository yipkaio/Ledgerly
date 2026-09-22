export type MonthTotal = { month: string; total_cents: number; receipt_count: number };
export type PeriodMode = "month" | "quarter" | "year";
export type DateBounds = { first: string | null; last: string | null };
export type DateRange = { from: string; to: string };
export type DateRangePreset = "all" | "month" | "three_months" | "year" | "custom";
export type TrendRow = MonthTotal & { label: string };
export const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function periodTotals(items: MonthTotal[], mode: PeriodMode, year: string, part: number) {
  const rows = items.filter((item) => {
    const month = Number(item.month.slice(5));
    return item.month.slice(0, 4) === year && (mode === "year" ||
      (mode === "month" ? month === part : Math.ceil(month / 3) === part));
  });
  return rows.reduce((total, item) => ({ total_cents: total.total_cents + item.total_cents,
    receipt_count: total.receipt_count + item.receipt_count }), { total_cents: 0, receipt_count: 0 });
}

export function periodLabel(mode: PeriodMode, year: string, part: number) {
  return mode === "year" ? year : mode === "quarter" ? `Q${part} ${year}` : `${monthNames[part - 1]} ${year}`;
}

function isoDate(year: number, month: number, day: number) {
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10);
}

export function presetDateRange(preset: DateRangePreset, bounds: DateBounds): DateRange {
  if (!bounds.first || !bounds.last || preset === "custom") return { from: "", to: "" };
  if (preset === "all") return { from: bounds.first, to: bounds.last };
  const latest = new Date(`${bounds.last}T00:00:00Z`);
  if (preset === "month") {
    return { from: isoDate(latest.getUTCFullYear(), latest.getUTCMonth(), 1), to: bounds.last };
  }
  if (preset === "three_months") {
    return { from: isoDate(latest.getUTCFullYear(), latest.getUTCMonth() - 2, 1), to: bounds.last };
  }
  return { from: `${latest.getUTCFullYear()}-01-01`, to: bounds.last };
}

function displayDate(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return `${day} ${monthNames[month - 1]} ${year}`;
}

export function dateRangeLabel(range: DateRange, bounds: DateBounds, allTime = false) {
  const from = range.from || bounds.first;
  const to = range.to || bounds.last;
  if (!from || !to) return "No dated accepted receipts";
  return `${allTime ? "All time · " : ""}${displayDate(from)} – ${displayDate(to)}`;
}

export function trendSeries(items: MonthTotal[], range: DateRange): TrendRow[] {
  if (!items.length) return [];
  const byMonth = new Map(items.map((item) => [item.month, item]));
  const first = (range.from || items[0].month).slice(0, 7);
  const last = (range.to || items.at(-1)!.month).slice(0, 7);
  const cursor = new Date(`${first}-01T00:00:00Z`);
  const end = new Date(`${last}-01T00:00:00Z`);
  const months: MonthTotal[] = [];
  while (cursor <= end) {
    const month = cursor.toISOString().slice(0, 7);
    months.push(byMonth.get(month) || { month, total_cents: 0, receipt_count: 0 });
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  if (months.length <= 24) {
    const showYear = new Set(months.map((item) => item.month.slice(0, 4))).size > 1;
    return months.map((item) => ({
      ...item,
      label: `${monthNames[Number(item.month.slice(5)) - 1]}${showYear ? ` ${item.month.slice(0, 4)}` : ""}`,
    }));
  }
  const years = new Map<string, MonthTotal>();
  for (const item of months) {
    const year = item.month.slice(0, 4);
    const total = years.get(year) || { month: year, total_cents: 0, receipt_count: 0 };
    total.total_cents += item.total_cents;
    total.receipt_count += item.receipt_count;
    years.set(year, total);
  }
  return [...years.values()].map((item) => ({ ...item, label: item.month }));
}
