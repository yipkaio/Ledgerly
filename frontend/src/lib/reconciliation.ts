import type { Extraction } from "./api";

function cents(value: number) {
  return Math.round((value + Math.sign(value) * Number.EPSILON) * 100);
}

export function reconciliation(data: Extraction) {
  const required = [data.subtotal, data.tax_amount, data.total_amount];
  const optional = [
    data.discount_amount,
    data.rounding_adjustment,
    data.total_before_rounding,
  ];
  if (
    required.some((value) => value == null || !Number.isFinite(value)) ||
    optional.some((value) => value != null && !Number.isFinite(value))
  )
    return {
      status: "incomplete",
      expected: null,
      difference: null,
      beforeRoundingDifference: null,
    } as const;
  const before =
    cents(data.subtotal!) -
    cents(data.discount_amount ?? 0) +
    cents(data.tax_amount!);
  const expected = before + cents(data.rounding_adjustment ?? 0);
  const difference = cents(data.total_amount!) - expected;
  const beforeDifference =
    data.total_before_rounding == null
      ? null
      : cents(data.total_before_rounding) - before;
  return {
    status:
      Math.abs(difference) <= 2 &&
      (beforeDifference == null || Math.abs(beforeDifference) <= 2)
        ? "matched"
        : "mismatch",
    expected: expected / 100,
    difference: difference / 100,
    beforeRoundingDifference:
      beforeDifference == null ? null : beforeDifference / 100,
  } as const;
}
