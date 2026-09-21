import assert from "node:assert/strict";
import test from "node:test";
import { periodTotals, periodLabel } from "../src/lib/dashboard-periods.ts";

const rows = [
  { month: "2025-01", total_cents: 10000, receipt_count: 1 },
  { month: "2026-01", total_cents: 20000, receipt_count: 2 },
  { month: "2026-03", total_cents: 30000, receipt_count: 3 },
  { month: "2026-04", total_cents: 40000, receipt_count: 4 },
  { month: "2026-12", total_cents: 50000, receipt_count: 5 },
];
test("month selection keeps years distinct", () => {
  assert.deepEqual(periodTotals(rows, "month", "2025", 1), { total_cents: 10000, receipt_count: 1 });
  assert.deepEqual(periodTotals(rows, "month", "2026", 1), { total_cents: 20000, receipt_count: 2 });
});
test("quarters respect boundaries and full years include every month", () => {
  assert.equal(periodTotals(rows, "quarter", "2026", 1).total_cents, 50000);
  assert.equal(periodTotals(rows, "quarter", "2026", 2).total_cents, 40000);
  assert.equal(periodTotals(rows, "quarter", "2026", 4).total_cents, 50000);
  assert.deepEqual(periodTotals(rows, "year", "2026", 1), { total_cents: 140000, receipt_count: 14 });
});
test("missing periods are zero, and labels contain the year", () => {
  assert.deepEqual(periodTotals(rows, "month", "2026", 2), { total_cents: 0, receipt_count: 0 });
  assert.equal(periodLabel("month", "2026", 2), "Feb 2026");
  assert.equal(periodLabel("quarter", "2025", 4), "Q4 2025");
  assert.equal(periodLabel("year", "2025", 1), "2025");
});
