import assert from "node:assert/strict";
import test from "node:test";
import {
  dateRangeLabel,
  periodTotals,
  periodLabel,
  presetDateRange,
  trendSeries,
} from "../src/lib/dashboard-periods.ts";

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
test("date presets use the latest accepted receipt instead of the system clock", () => {
  const bounds = { first: "2018-09-12", last: "2026-09-18" };
  assert.deepEqual(presetDateRange("all", bounds), { from: bounds.first, to: bounds.last });
  assert.deepEqual(presetDateRange("month", bounds), {
    from: "2026-09-01",
    to: "2026-09-18",
  });
  assert.deepEqual(presetDateRange("three_months", bounds), {
    from: "2026-07-01",
    to: "2026-09-18",
  });
  assert.deepEqual(presetDateRange("year", bounds), {
    from: "2026-01-01",
    to: "2026-09-18",
  });
});
test("all-time labels identify the complete retained receipt range", () => {
  const bounds = { first: "2018-09-12", last: "2026-09-18" };
  assert.match(dateRangeLabel({ from: "", to: "" }, bounds, true), /^All time/);
  assert.match(
    dateRangeLabel({ from: "2026-09-01", to: "2026-09-18" }, bounds),
    /^1 Sep 2026/,
  );
});
test("trend series fills missing months and rolls long ranges into years", () => {
  assert.deepEqual(
    trendSeries(
      [
        { month: "2026-07", total_cents: 100, receipt_count: 1 },
        { month: "2026-09", total_cents: 300, receipt_count: 2 },
      ],
      { from: "2026-07-01", to: "2026-09-18" },
    ),
    [
      { month: "2026-07", total_cents: 100, receipt_count: 1, label: "Jul" },
      { month: "2026-08", total_cents: 0, receipt_count: 0, label: "Aug" },
      { month: "2026-09", total_cents: 300, receipt_count: 2, label: "Sep" },
    ],
  );
  const yearly = trendSeries(
    [
      { month: "2024-01", total_cents: 100, receipt_count: 1 },
      { month: "2026-02", total_cents: 300, receipt_count: 2 },
    ],
    { from: "2024-01-01", to: "2026-02-01" },
  );
  assert.deepEqual(yearly.map((item) => item.label), ["2024", "2025", "2026"]);
  assert.equal(yearly[2].total_cents, 300);
});
