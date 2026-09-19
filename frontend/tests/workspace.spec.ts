import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type {
  Amendment,
  AmendmentRequest,
  ReviewRequest,
} from "../src/lib/api";
const key = "test-only-key-not-a-real-secret-32-characters";
const id = "1d898e3a-66fa-4651-bb71-ca85d0a7770f";
const extraction = {
  vendor: "MR D.I.Y.",
  legal_entity: null,
  company_registration_number: null,
  branch: null,
  receipt_number: "R100",
  date: "2019-01-12",
  currency: "MYR",
  line_items: [
    {
      description: "Cleaning supplies",
      quantity: 1,
      unit_price: 33.92,
      discount_percent: null,
      discount_amount: null,
      line_total: 33.92,
    },
  ],
  subtotal: 33.92,
  discount_amount: null,
  tax_amount: null,
  total_before_rounding: 33.92,
  rounding_adjustment: -0.02,
  total_amount: 33.9,
  cash_tendered: 50,
  change_amount: 16.1,
  payment_method: "CASH",
  needs_review: false,
  review_reasons: [],
};
const original = {
  receipt_id: id,
  content_type: "image/jpeg",
  processing_status: "REVIEW_QUEUE",
  created_at: "2026-09-13T12:00:00Z",
  business_purpose: null,
  ocr_engine: "paddle",
  ocr_text: "MR D.I.Y. 33.90",
  error: null,
  extracted_data: extraction,
  classification: {
    category: "Office Supplies",
    confidence: 0.7,
    source: "llm",
    reason: "Mixed supplies; business use unclear.",
    needs_review: true,
    review_reasons: ["Business purpose is missing"],
    workflow_decision: "REVIEW_QUEUE",
  },
  review: null,
  review_version: 0,
};
// Tiny valid PNG; mock endpoints never call OCR or the paid gateway.
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jG1sAAAAASUVORK5CYII=",
  "base64",
);

test("reprocessing creates an unsaved review draft with reconciliation and provenance", async ({
  page,
}) => {
  const requests = await setup(page);
  await page
    .getByRole("button", { name: "Open receipt MR D.I.Y.", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Reprocess receipt", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(/may consume credits/)).toBeVisible();
  await dialog.getByLabel("Your name").fill("Tester");
  await dialog
    .getByLabel("Reason for reprocessing")
    .fill("Recover the newly supported receipt discount");
  await dialog
    .getByRole("button", { name: "Create extraction draft", exact: true })
    .click();
  await expect(
    page.getByText("Latest attempt · Draft ready for review"),
  ).toBeVisible();
  expect(requests).toHaveLength(0);
  await page
    .getByRole("button", { name: "Use draft for review", exact: true })
    .click();
  await expect(page.getByLabel("Vendor *")).toHaveValue("Reprocessed vendor");
  await expect(page.getByLabel("Discount amount", { exact: true })).toHaveValue(
    "10",
  );
  expect(requests).toHaveLength(0);
  await page.getByLabel("Reviewer name").fill("Tester");
  await page
    .getByLabel("Decision reason")
    .fill("Verified new extraction against the retained original receipt");
  await page.getByRole("checkbox").check();
  await page
    .getByRole("button", { name: "Approve receipt", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /Confirm approval/ })
    .click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].corrected_data?.discount_amount).toBe(10);
  expect(requests[0].reprocess_request_id).toBeTruthy();
});

test("monthly close shows evidence gaps, spend concentration, and grounded prompts", async ({ page }) => {
  await setup(page);
  await page.route("**/bank-statements/periods", (route) => route.fulfill({ json: { items: [{ month: "2026-09", currency: "SGD", statement_count: 1, transaction_count: 2 }] } }));
  await page.route("**/reconciliation?*", (route) => route.fulfill({ json: {
    month: "2026-09", currency: "SGD", generated_at: "2026-09-19T00:00:00Z",
    statements: [{ statement_id: "88d896c9-eb7f-4c22-996b-b89fbb8f77da", account_label: "Operating", original_filename: "sep.csv", uploaded_at: "2026-09-19T00:00:00Z", row_count: 2, skipped_rows: 0 }],
    totals: { bank_debits_cents: 15000, receipt_spend_cents: 12000, matched_cents: 10000, difference_cents: 3000, exception_count: 2 },
    transactions: [
      { transaction_id: "t1", posted_date: "2026-09-03", description: "Acme", amount_cents: 10000, reference: null, receipt_id: id, receipt_vendor: "Acme", status: "MATCHED" },
      { transaction_id: "t2", posted_date: "2026-09-04", description: "Unknown", amount_cents: 5000, reference: null, receipt_id: null, receipt_vendor: null, status: "MISSING_RECEIPT" },
    ],
    receipts: [{ receipt_id: id, receipt_date: "2026-09-03", vendor: "Acme", category: "Repairs and Maintenance", amount_cents: 12000, status: "NO_BANK_MATCH", transaction_id: null, duplicate_receipt: false }],
    categories: [{ category: "Repairs and Maintenance", total_cents: 12000 }],
    vendors: [{ vendor: "Acme", total_cents: 12000 }],
    suggestions: [{ title: "Review Repairs and Maintenance", detail: "It is the largest category. Compare recurring charges and request fresh quotes." }],
  } }));
  await page.getByRole("button", { name: "Monthly close", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Monthly close" })).toBeVisible();
  await expect(page.getByText("SGD 150.00", { exact: true })).toBeVisible();
  await expect(page.getByText(/^missing receipt$/i)).toBeVisible();
  await expect(page.getByText("Highest spend by company")).toBeVisible();
  await expect(page.getByText("Review Repairs and Maintenance", { exact: true })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("default currency consolidates spend with a dated rate snapshot", async ({ page }) => {
  await setup(page);
  let defaultCurrency = "SGD";
  await page.route("**/workspace/settings", async (route) => {
    defaultCurrency = route.request().postDataJSON().default_currency;
    await route.fulfill({ json: { default_currency: defaultCurrency, updated_at: "2026-09-19T00:00:00Z" } });
  });
  await page.route("**/dashboard", (route) => route.fulfill({ json: {
    total_receipts: 2, counts: { AUTO_FILED: 2, APPROVED: 0, REJECTED: 0, REVIEW_QUEUE: 0, PROCESSING: 0, FAILED: 0 },
    accepted_missing_value: 0, generated_at: "2026-09-19T00:00:00Z", default_currency: defaultCurrency,
    currencies: [
      { currency: "SGD", total_cents: 15000, receipt_count: 1, categories: [{ category: "Office Supplies", total_cents: 15000 }], months: [{ month: "2026-09", total_cents: 15000 }] },
      { currency: "MYR", total_cents: 50000, receipt_count: 1, categories: [{ category: "Repairs and Maintenance", total_cents: 50000 }], months: [{ month: "2026-09", total_cents: 50000 }] },
    ],
    reporting: { currency: defaultCurrency, available: true, total_cents: defaultCurrency === "SGD" ? 30000 : 100000, receipt_count: 2,
      categories: [{ category: "Repairs and Maintenance", total_cents: defaultCurrency === "SGD" ? 15000 : 50000 }],
      months: [{ month: "2026-09", total_cents: defaultCurrency === "SGD" ? 30000 : 100000 }],
      as_of: "2026-09-18", source: "European Central Bank", stale: false, components: [] },
  } }));
  await page.getByRole("button", { name: "Main dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "SGD 300.00" })).toBeVisible();
  await expect(page.getByText(/reference rates dated 2026-09-18/)).toBeVisible();
  await page.getByLabel("Default currency").selectOption("MYR");
  await expect(page.getByRole("heading", { name: "MYR 1000.00" })).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
async function setup(page: Page, mode = "success") {
  const reprocessing: Record<string, unknown>[] = [];
  let review: Record<string, unknown> | null = null;
  let amendment: Amendment | null = null;
  const requests: ReviewRequest[] = [];
  await page.route("**/dashboard", (route) =>
    route.fulfill({
      json: {
        total_receipts: 21,
        counts: {
          AUTO_FILED: 19,
          APPROVED: 0,
          REJECTED: 1,
          REVIEW_QUEUE: 1,
          PROCESSING: 0,
          FAILED: 0,
        },
        accepted_missing_value: 0,
        generated_at: "2026-09-13T14:00:00Z",
        currencies: [
          {
            currency: "MYR",
            total_cents: 3390,
            receipt_count: 18,
            categories: [{ category: "Office Supplies", total_cents: 3390 }],
            months: [{ month: "2019-01", total_cents: 3390 }],
          },
          {
            currency: "SGD",
            total_cents: 1000,
            receipt_count: 1,
            categories: [{ category: "Utilities", total_cents: 1000 }],
            months: [{ month: "2026-09", total_cents: 1000 }],
          },
        ],
      },
    }),
  );
  await page.route(/\/(receipts|reviews)(\/?|\?.*)$/, async (route) => {
    const url = new URL(route.request().url());
    const row = {
      receipt_id: id,
      vendor: "MR D.I.Y.",
      created_at: original.created_at,
      currency: "MYR",
      total_amount: 33.9,
      decision: "REVIEW_QUEUE",
      review_decision: review?.decision,
    };
    await route.fulfill({
      json: {
        items: url.pathname === "/reviews" && review ? [] : [row],
        total: url.searchParams.get("offset") === "20" ? 21 : 21,
        offset: Number(url.searchParams.get("offset") || 0),
        limit: 20,
      },
    });
  });
  await page.route(`**/receipts/${id}`, (route) =>
    route.fulfill({
      json: {
        ...original,
        review,
        review_version: review ? 1 : 0,
        amendment,
        record_version: amendment ? 2 : review ? 1 : 0,
        effective_data:
          amendment?.final_data ||
          review?.final_data ||
          original.extracted_data,
        effective_category:
          amendment?.category ||
          review?.category ||
          original.classification.category,
        duplicate_candidates: [],
        reprocessing,
      },
    }),
  );
  await page.route(`**/receipts/${id}/reprocess`, (route) => {
    const body = route.request().postDataJSON();
    const result = {
      ...body,
      status: "SUCCEEDED",
      started_at: new Date().toISOString(),
      expires_at: new Date(Date.now() + 600000).toISOString(),
      error: null,
      extracted_data: {
        ...extraction,
        vendor: "Reprocessed vendor",
        subtotal: 50,
        discount_amount: 10,
        tax_amount: 0,
        total_before_rounding: 40,
        rounding_adjustment: 0,
        total_amount: 40,
        cash_tendered: null,
        change_amount: null,
      },
    };
    reprocessing.unshift(result);
    return route.fulfill({ json: result });
  });
  await page.route(`**/receipts/${id}/image`, (route) =>
    route.fulfill({
      contentType: "image/png",
      body: png,
      status: mode === "missing-image" ? 404 : 200,
    }),
  );
  await page.route(`**/receipts/${id}/preview`, (route) =>
    route.fulfill({
      contentType: "image/png",
      body: png,
      status: mode === "missing-image" ? 404 : 200,
    }),
  );
  await page.route(`**/receipts/${id}/reviews`, (route) =>
    route.fulfill({
      json: {
        items: review
          ? [
              {
                ...review,
                before: {
                  extracted_data: extraction,
                  classification: original.classification,
                },
              },
            ]
          : [],
      },
    }),
  );
  await page.route(`**/receipts/${id}/amendments`, async (route) => {
    if (route.request().method() === "GET") {
      await route.fulfill({ json: { items: amendment ? [amendment] : [] } });
      return;
    }
    const payload = route.request().postDataJSON() as AmendmentRequest;
    amendment = {
      ...payload,
      event_type: "AMENDMENT",
      record_version: 2,
      amended_at: "2026-09-13T15:00:00Z",
      identity_source: "self_reported",
      validation_issues: [],
      before: {
        record_version: 1,
        state: "APPROVED",
        final_data: review?.final_data || extraction,
        category: String(review?.category || "Office Supplies"),
      },
    } as Amendment;
    await route.fulfill({ json: amendment });
  });
  await page.route(`**/receipts/${id}/review`, async (route) => {
    const payload = route.request().postDataJSON() as ReviewRequest;
    requests.push(payload);
    expect(route.request().headers()["x-api-key"]).toBe(key);
    if (mode === "lost" && requests.length === 1) {
      await route.abort("failed");
      return;
    }
    if (mode === "invalid") {
      await route.fulfill({
        status: 422,
        json: { detail: "Line item total does not reconcile" },
      });
      return;
    }
    if (mode === "conflict") {
      await route.fulfill({
        status: 409,
        json: { detail: "Already finalized" },
      });
      return;
    }
    review = {
      ...payload,
      review_version: 1,
      final_data: payload.corrected_data || null,
      reviewed_at: "2026-09-13T14:00:00Z",
      identity_source: "self_reported",
      validation_issues: [],
      override_reason: null,
    };
    await route.fulfill({ json: review });
  });
  await page.goto("/ui/");
  await page.getByLabel("App API key").fill(key);
  await page.getByRole("button", { name: "Connect to workspace" }).click();
  await expect(
    page.getByRole("heading", { name: "Main dashboard" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Receipt history" }),
  ).toBeVisible();
  return requests;
}
async function open(page: Page) {
  await page
    .getByRole("button", { name: "Pending reviews", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Review receipt MR D.I.Y.",
      exact: true,
    })
    .click();
  await expect(page.getByLabel("Vendor *")).toHaveValue("MR D.I.Y.");
  await page.getByLabel("Reviewer name").fill("Yip Kai");
  await page
    .getByLabel("Decision reason")
    .fill("Checked receipt and confirmed supplies used for office cleaning.");
  await page.getByRole("checkbox").check();
}
test("approval edits, automatic UUID, final audit and no persistent key", async ({
  page,
}) => {
  const sent = await setup(page);
  await open(page);
  await page.getByLabel("Vendor *").fill("Verified MR D.I.Y.");
  await page.getByLabel("Discount amount", { exact: true }).fill("2.00");
  await page.getByLabel("Rounding adjustment").focus();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.type("-0.02");
  await expect(page.getByLabel("Rounding adjustment")).toHaveValue("-0.02");
  await page.getByLabel("Item 1 quantity").fill("2");
  await page.getByLabel("Item 1 unit price").fill("16.96");
  await page.getByRole("button", { name: "Approve receipt" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText(/Approved by Yip Kai/)).toBeVisible();
  expect(sent).toHaveLength(1);
  expect(sent[0].request_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(sent[0].corrected_data?.vendor).toBe("Verified MR D.I.Y.");
  expect(sent[0].expected_version).toBe(0);
  expect(sent[0].corrected_data?.line_items[0].quantity).toBe(2);
  expect(sent[0].corrected_data?.line_items[0].unit_price).toBe(16.96);
  expect(sent[0].corrected_data?.line_items[0].discount_percent).toBeNull();
  expect(sent[0].corrected_data?.discount_amount).toBe(2);
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  await page.getByRole("button", { name: "Disconnect" }).click();
  await expect(page.getByLabel("App API key")).toHaveValue("");
});

test("history filters and selected Excel export preserve explicit scope", async ({
  page,
}) => {
  await setup(page);
  await page.getByLabel("Vendor, receipt number or ID").fill("MR D.I.Y.");
  await page.getByLabel("Currency").fill("MYR");
  await page.getByLabel("Category").click();
  await page.getByRole("option", { name: "Office Supplies" }).click();
  const filtered = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return (
      url.pathname === "/receipts" &&
      url.searchParams.get("query") === "MR D.I.Y." &&
      url.searchParams.get("currency") === "MYR" &&
      url.searchParams.get("category") === "Office Supplies"
    );
  });
  await page.getByRole("button", { name: "Apply filters" }).click();
  await filtered;

  let exported: unknown = null;
  await page.route("**/receipts/export", async (route) => {
    exported = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType:
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      headers: {
        "Content-Disposition": 'attachment; filename="receipt-history.xlsx"',
      },
      body: Buffer.from("safe-test-workbook"),
    });
  });
  await page.getByLabel("Select receipt MR D.I.Y.").check();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export selected" }).click();
  expect((await download).suggestedFilename()).toBe("receipt-history.xlsx");
  expect(exported).toEqual({ receipt_ids: [id] });
  await expect(page.getByText("1 selected across pages")).toBeVisible();
  await page.getByRole("button", { name: "Clear selection" }).click();
  await expect(page.getByText("0 selected across pages")).toBeVisible();
});

test("approved receipt can be amended while earlier review remains visible", async ({
  page,
}) => {
  await setup(page);
  await open(page);
  await page.getByRole("button", { name: "Approve receipt" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  await page.getByRole("button", { name: "Open receipt MR D.I.Y." }).click();
  await expect(
    page.getByRole("heading", { name: "Receipt details" }),
  ).toBeVisible();
  await expect(page.getByLabel("Vendor *")).toHaveCount(0);
  await page.getByRole("button", { name: "Create amendment" }).click();
  await expect(
    page.getByRole("button", { name: "Save amendment" }),
  ).toBeVisible();
  await page.getByLabel("Vendor *").fill("Amended MR D.I.Y.");
  await page.getByLabel("Reviewer name").fill("Yip Kai");
  await page
    .getByLabel("Amendment reason")
    .fill("Corrected vendor wording after checking the original image.");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Save amendment" }).click();
  await page.getByRole("button", { name: "Confirm amendment" }).click();
  await expect(
    page.getByText(/Effective data amended by Yip Kai/),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Amended MR D.I.Y." }),
  ).toBeVisible();
  await expect(
    page.getByText(/Version 2; every earlier version remains in the audit/),
  ).toBeVisible();
  await expect(page.getByText("Vendor", { exact: true }).last()).toBeVisible();
  await expect(
    page.getByText("MR D.I.Y.", { exact: true }).last(),
  ).toBeVisible();
  await expect(page.getByText("Version 1 → 2")).toBeVisible();
  await expect(page.getByText("Original and final audit data")).toHaveCount(0);
});

test("dashboard totals stay separate by currency and links open the queue", async ({
  page,
}) => {
  await setup(page);
  await page
    .getByRole("button", { name: "Main dashboard", exact: true })
    .click();
  await expect(
    page.getByText("MYR 33.90", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByLabel("Dashboard view", { exact: true })
    .selectOption("SGD");
  await expect(
    page.getByText("SGD 10.00", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("MYR 33.90", { exact: true })).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page
    .getByRole("button", { name: /Pending reviews.*Needs a human decision/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "Pending reviews" }),
  ).toBeVisible();
});

test("anchored preview loads on hover and closes with Escape", async ({
  page,
}) => {
  await setup(page);
  let images = 0;
  page.on("request", (req) => {
    if (req.url().endsWith("/preview")) images += 1;
  });
  expect(images).toBe(0);
  await page.getByRole("button", { name: "Preview receipt MR D.I.Y." }).hover();
  await expect(
    page.getByAltText("Quick preview of original receipt"),
  ).toBeVisible();
  // React StrictMode aborts the first effect during development; production loads once.
  expect(images).toBeGreaterThanOrEqual(1);
  expect(images).toBeLessThanOrEqual(2);
  const preview = page.getByRole("dialog", {
    name: "Receipt preview for MR D.I.Y.",
  });
  const box = await preview.boundingBox();
  expect(box?.width).toBeLessThanOrEqual(288);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(preview).not.toBeVisible();
});

test("preview supports keyboard and small screens without relying on hover", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await setup(page);
  const trigger = page.getByRole("button", {
    name: "Preview receipt MR D.I.Y.",
  });
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByAltText("Quick preview of original receipt"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Close receipt preview" }),
  ).toBeFocused();
  const box = await page
    .getByRole("dialog", { name: "Receipt preview for MR D.I.Y." })
    .boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(375);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Open full receipt" }).click();
  await expect(
    page.getByRole("heading", { name: "Receipt details" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "MR D.I.Y." })).toBeVisible();
  await expect(page.getByText("OCR text", { exact: false })).toHaveCount(0);
});
test("rejection excludes corrected fields and preserves the audit", async ({
  page,
}) => {
  const sent = await setup(page);
  await open(page);
  await page
    .getByLabel("Decision reason")
    .fill("Confirmed personal purchase; not a business expense.");
  await page.getByRole("button", { name: "Reject receipt" }).click();
  await page.getByRole("button", { name: "Confirm rejection" }).click();
  await expect(page.getByText(/Rejected by Yip Kai/)).toBeVisible();
  await expect(
    page.getByRole("alert").filter({ hasText: "Rejected by Yip Kai" }),
  ).toHaveClass(/text-red-950/);
  expect(sent[0].decision).toBe("REJECTED");
  expect(sent[0]).not.toHaveProperty("corrected_data");
  expect(sent[0]).not.toHaveProperty("category");
});
test("lost response retries identical frozen payload", async ({ page }) => {
  const sent = await setup(page, "lost");
  await open(page);
  await page.getByRole("button", { name: "Approve receipt" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByLabel("Vendor *")).toBeDisabled();
  await page.getByRole("button", { name: "Retry same change" }).click();
  await expect(page.getByText(/Approved by Yip Kai/)).toBeVisible();
  expect(sent).toHaveLength(2);
  expect(sent[0]).toEqual(sent[1]);
});
test("validation retains edits; stale conflict requires reload", async ({
  page,
}) => {
  await setup(page, "invalid");
  await open(page);
  await page.getByLabel("Vendor *").fill("Corrected vendor");
  await page.getByRole("button", { name: "Approve receipt" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByRole("alert")).toContainText("does not reconcile");
  await expect(page.getByLabel("Vendor *")).toHaveValue("Corrected vendor");
  await expect(page.getByLabel("Vendor *")).toBeEnabled();
});
test("conflict blocks another decision until refreshed", async ({ page }) => {
  await setup(page, "conflict");
  await open(page);
  await page.getByRole("button", { name: "Approve receipt" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByRole("alert")).toContainText("Reload");
  await expect(
    page.getByRole("button", { name: "Approve receipt" }),
  ).toBeDisabled();
});
test("missing image blocks evidence confirmation and approval", async ({
  page,
}) => {
  await setup(page, "missing-image");
  await page
    .getByRole("button", { name: "Pending reviews", exact: true })
    .click();
  await page
    .getByRole("button", {
      name: "Review receipt MR D.I.Y.",
      exact: true,
    })
    .click();
  await expect(page.getByRole("checkbox")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Approve receipt" }),
  ).toBeDisabled();
});
test("keyboard dialog focus, Escape and mobile accessibility", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await setup(page);
  await open(page);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.getByRole("button", { name: "Approve receipt" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Tab");
  expect(
    await page.evaluate(
      () => !!document.activeElement?.closest('[role="dialog"]'),
    ),
  ).toBe(true);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
});
test("upload multipart purpose and saved receipt; pagination", async ({
  page,
}) => {
  await setup(page);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("21–21 of 21")).toBeVisible();
  await page.route("**/receipts/upload", async (route) => {
    expect(route.request().headers()["x-api-key"]).toBe(key);
    expect(route.request().postData()).toContain(
      "Mock purpose: office cleaning",
    );
    await route.fulfill({ status: 202, json: { receipt_id: id } });
  });
  await page
    .getByRole("button", { name: "Upload receipt", exact: true })
    .click();
  await page
    .getByLabel("Receipt file", { exact: true })
    .setInputFiles({ name: "receipt.png", mimeType: "image/png", buffer: png });
  await page
    .getByLabel("Business purpose (optional)")
    .fill("Mock purpose: office cleaning");
  await page.getByRole("button", { name: "Upload and process" }).click();
  await expect(
    page.getByRole("heading", { name: "Receipt details" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "MR D.I.Y." })).toBeVisible();
});

test("history is read only, hides OCR, and presents a structured receipt summary", async ({
  page,
}) => {
  await setup(page);
  await page.getByRole("button", { name: "Open receipt MR D.I.Y." }).click();
  await expect(
    page.getByRole("heading", { name: "Receipt details" }),
  ).toBeVisible();
  await expect(page.getByText("Effective receipt record")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Merchant details" }),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Line items" })).toBeVisible();
  await expect(page.getByText("OCR text", { exact: false })).toHaveCount(0);
  await expect(page.getByLabel("Vendor *")).toHaveCount(0);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("navigation warns before discarding review edits", async ({ page }) => {
  await setup(page);
  await open(page);
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Back to list" }).click();
  await expect(page.getByLabel("Reviewer name")).toHaveValue("Yip Kai");
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Back to list" }).click();
  await expect(
    page.getByRole("heading", { name: "Pending reviews" }),
  ).toBeVisible();
});

test("late upload response does not navigate away from the current screen", async ({
  page,
}) => {
  await setup(page);
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  let started!: () => void;
  const start = new Promise<void>((resolve) => {
    started = resolve;
  });
  await page.route("**/receipts/upload", async (route) => {
    started();
    await wait;
    await route.fulfill({ status: 202, json: { receipt_id: id } });
  });
  await page
    .getByRole("button", { name: "Upload receipt", exact: true })
    .click();
  await page
    .getByLabel("Receipt file", { exact: true })
    .setInputFiles({ name: "receipt.png", mimeType: "image/png", buffer: png });
  await page.getByRole("button", { name: "Upload and process" }).click();
  await start;
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  const response = page.waitForResponse("**/receipts/upload");
  release();
  await response;
  await expect(
    page.getByRole("heading", { name: "Receipt history" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Review receipt" }),
  ).not.toBeVisible();
});
