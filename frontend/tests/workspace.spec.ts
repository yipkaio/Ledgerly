import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import type { ReviewRequest } from "../src/lib/api";
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
async function setup(page: Page, mode = "success") {
  let review: Record<string, unknown> | null = null;
  const requests: ReviewRequest[] = [];
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
      json: { ...original, review, review_version: review ? 1 : 0 },
    }),
  );
  await page.route(`**/receipts/${id}/image`, (route) =>
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
    page.getByRole("heading", { name: "Receipt history" }),
  ).toBeVisible();
  return requests;
}
async function open(page: Page) {
  await page.getByRole("button", { name: "Open receipt MR D.I.Y." }).click();
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
  await expect(
    page.getByText("This decision is final.", { exact: false }),
  ).toBeVisible();
  expect(sent).toHaveLength(1);
  expect(sent[0].request_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(sent[0].corrected_data?.vendor).toBe("Verified MR D.I.Y.");
  expect(sent[0].expected_version).toBe(0);
  expect(sent[0].corrected_data?.line_items[0].quantity).toBe(2);
  expect(sent[0].corrected_data?.line_items[0].unit_price).toBe(16.96);
  expect(sent[0].corrected_data?.line_items[0].discount_percent).toBeNull();
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  await page.getByRole("button", { name: "Disconnect" }).click();
  await expect(page.getByLabel("App API key")).toHaveValue("");
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
  await expect(
    page.getByText("This decision is final.", { exact: false }),
  ).toBeVisible();
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
  await page.getByRole("button", { name: "Retry same decision" }).click();
  await expect(
    page.getByText("This decision is final.", { exact: false }),
  ).toBeVisible();
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
  await page.getByRole("button", { name: "Open receipt MR D.I.Y." }).click();
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
    .getByLabel("Receipt image", { exact: true })
    .setInputFiles({ name: "receipt.png", mimeType: "image/png", buffer: png });
  await page
    .getByLabel("Business purpose (optional)")
    .fill("Mock purpose: office cleaning");
  await page.getByRole("button", { name: "Upload and process" }).click();
  await expect(page.getByLabel("Vendor *")).toHaveValue("MR D.I.Y.");
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
    page.getByRole("heading", { name: "Receipt history" }),
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
    .getByLabel("Receipt image", { exact: true })
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
