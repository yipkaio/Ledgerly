export type MonthTotal = { month: string; total_cents: number; receipt_count: number };
export type PeriodMode = "month" | "quarter" | "year";
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
