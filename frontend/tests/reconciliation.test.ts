import assert from "node:assert/strict";
import { test } from "node:test";
import { reconciliation } from "../src/lib/reconciliation.ts";
import type { Extraction } from "../src/lib/api.ts";

const base = {
  subtotal: 935,
  discount_amount: 50,
  tax_amount: 79.65,
  rounding_adjustment: null,
  total_amount: 964.65,
  total_before_rounding: 964.65,
} as Extraction;
test("discount, signed rounding and cents reconcile", () => {
  assert.equal(reconciliation(base).status, "matched");
  assert.equal(
    reconciliation({ ...base, rounding_adjustment: -0.05, total_amount: 964.6 })
      .difference,
    0,
  );
  assert.equal(
    reconciliation({ ...base, total_amount: 965 }).status,
    "mismatch",
  );
});
test("unknown tax and missing totals are incomplete, explicit zero works", () => {
  assert.equal(
    reconciliation({ ...base, tax_amount: null }).status,
    "incomplete",
  );
  assert.equal(
    reconciliation({ ...base, subtotal: null }).status,
    "incomplete",
  );
  assert.equal(
    reconciliation({
      ...base,
      subtotal: 0,
      discount_amount: null,
      tax_amount: 0,
      total_amount: 0,
      total_before_rounding: 0,
    }).status,
    "matched",
  );
});
test("two-cent tolerance and intermediate mismatches", () => {
  assert.equal(
    reconciliation({ ...base, total_amount: 964.67 }).status,
    "matched",
  );
  assert.equal(
    reconciliation({ ...base, total_amount: 964.68 }).status,
    "mismatch",
  );
  assert.equal(
    reconciliation({ ...base, total_before_rounding: 1000 }).status,
    "mismatch",
  );
});
