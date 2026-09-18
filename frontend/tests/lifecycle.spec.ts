import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const id = "1d898e3a-66fa-4651-bb71-ca85d0a7770f";
test("delete, restore, void protection and mobile confirmation", async ({
  page,
}) => {
  let state = "ACTIVE";
  let version = 0;
  const events: object[] = [];
  let accepted = false;
  const purge = new Date(Date.now() + 30 * 86400000).toISOString();
  const data = {
    vendor: "Sample Tech",
    receipt_number: "TEST-001",
    date: "2026-09-18",
    currency: "SGD",
    line_items: [],
    subtotal: 50,
    discount_amount: null,
    tax_amount: 0,
    total_before_rounding: 50,
    rounding_adjustment: 0,
    total_amount: 50,
    needs_review: false,
    review_reasons: [],
  };
  await page.route("**/dashboard", (route) =>
    route.fulfill({
      json: {
        total_receipts: 1,
        counts: {},
        currencies: [],
        accepted_missing_value: 0,
      },
    }),
  );
  await page.route(/\/receipts\?.*/, (route) => {
    const deleted =
      new URL(route.request().url()).searchParams.get("state") === "DELETED";
    const visible = deleted ? state === "DELETED" : state !== "DELETED";
    return route.fulfill({
      json: {
        items: visible
          ? [
              {
                receipt_id: id,
                vendor: data.vendor,
                created_at: "2026-09-18T00:00:00Z",
                total_amount: 50,
                currency: "SGD",
                workflow_state:
                  state === "ACTIVE"
                    ? accepted
                      ? "AUTO_FILED"
                      : "FAILED"
                    : state,
                purge_after: purge,
              },
            ]
          : [],
        total: visible ? 1 : 0,
        offset: 0,
        limit: 20,
      },
    });
  });
  await page.route(`**/receipts/${id}`, (route) =>
    route.fulfill({
      json: {
        receipt_id: id,
        content_type: "image/jpeg",
        processing_status: accepted ? "COMPLETED" : "FAILED",
        created_at: "2026-09-18T00:00:00Z",
        extracted_data: data,
        effective_data: data,
        classification: accepted
          ? {
              workflow_decision: "AUTO_FILED",
              category: "Office Supplies",
              confidence: 1,
              source: "lookup",
              reason: "Known vendor",
            }
          : null,
        review: null,
        amendment: null,
        record_version: 0,
        review_version: 0,
        lifecycle_state: state,
        lifecycle_version: version,
        purge_after: state === "DELETED" ? purge : null,
        lifecycle_events: events,
      },
    }),
  );
  await page.route(`**/receipts/${id}/reviews`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`**/receipts/${id}/amendments`, (route) =>
    route.fulfill({ json: { items: [] } }),
  );
  await page.route(`**/receipts/${id}/image`, (route) =>
    route.fulfill({ status: 404 }),
  );
  await page.route(`**/receipts/${id}/lifecycle`, (route) => {
    const body = route.request().postDataJSON();
    expect(body.expected_version).toBe(version);
    expect(body.reason.length).toBeGreaterThanOrEqual(10);
    state =
      body.action === "DELETE"
        ? "DELETED"
        : body.action === "VOID"
          ? "VOIDED"
          : "ACTIVE";
    version++;
    const event = { ...body, version, occurred_at: new Date().toISOString() };
    events.push(event);
    return route.fulfill({ json: event });
  });
  await page.goto("/ui/");
  await page
    .getByLabel("App API key")
    .fill("test-key-never-a-real-secret-123456789");
  await page.getByRole("button", { name: "Connect to workspace" }).click();
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open receipt Sample Tech", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Move to deleted receipts", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", {
      name: "Move to deleted receipts",
      exact: true,
    }),
  ).toBeDisabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await dialog.getByLabel("Your name").fill("Tester");
  await dialog
    .getByLabel("Reason", { exact: true })
    .fill("Duplicate synthetic test record");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await page.screenshot({
    path: "test-results/lifecycle-mobile.png",
    fullPage: true,
  });
  await dialog
    .getByRole("button", { name: "Move to deleted receipts", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "In deleted receipts" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Deleted receipts", exact: true })
    .click();
  await expect(page.getByText("days remaining")).toBeVisible();
  await page
    .getByRole("button", { name: "Open receipt Sample Tech", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Restore receipt", exact: true })
    .click();
  await dialog.getByLabel("Your name").fill("Tester");
  await dialog
    .getByLabel("Reason", { exact: true })
    .fill("Restoring valid synthetic record");
  await dialog
    .getByRole("button", { name: "Restore receipt", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Manage this receipt" }),
  ).toBeVisible();
  accepted = true;
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Open receipt Sample Tech", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Move to deleted receipts", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Void receipt", exact: true }).click();
  await dialog.getByLabel("Your name").fill("Tester");
  await dialog
    .getByLabel("Reason", { exact: true })
    .fill("Accidentally finalized test expense");
  await dialog
    .getByRole("button", { name: "Void receipt", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Voided · evidence retained" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create amendment" }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Back to list" }).click();
  await expect(
    page.getByLabel("Select receipt Sample Tech", { exact: true }),
  ).toBeDisabled();
});
