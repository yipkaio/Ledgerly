import { expect, test } from "@playwright/test";

const key = "test-only-key-not-a-real-secret-32-characters";
const receipts = [
  { date: "2018-09-10", cents: 153, category: "Meals and Entertainment" },
  { date: "2026-09-18", cents: 8720, category: "Meals and Entertainment" },
  { date: "2026-09-18", cents: 234568, category: "Office Supplies" },
  { date: "2026-10-02", cents: 10000, category: "Travel and Transport" },
];

test("one date range drives spend, chart, count and accepted history", async ({ page }) => {
  await page.route("**/auth/config", (route) => route.fulfill({ json: { mode: "api_key" } }));
  await page.route("**/receipts?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({
      json: {
        items: [],
        total: params.has("state") ? Number(params.get("date_from") === "2026-09-01" ? 2 : 4) : 4,
        offset: 0,
        limit: 20,
      },
    });
  });
  let lastDashboardQuery = "";
  await page.route("**/dashboard?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    lastDashboardQuery = params.toString();
    const first = params.get("date_from");
    const last = params.get("date_to");
    const dated = receipts.filter((receipt) => (!first || receipt.date >= first) && (!last || receipt.date <= last));
    const months = new Map<string, { month: string; total_cents: number; receipt_count: number }>();
    const categories = new Map<string, number>();
    for (const receipt of dated) {
      const month = receipt.date.slice(0, 7);
      const current = months.get(month) || { month, total_cents: 0, receipt_count: 0 };
      current.total_cents += receipt.cents;
      current.receipt_count += 1;
      months.set(month, current);
      categories.set(receipt.category, (categories.get(receipt.category) || 0) + receipt.cents);
    }
    const total = dated.reduce((sum, item) => sum + item.cents, 0);
    const currency = {
      currency: "SGD",
      total_cents: total,
      receipt_count: dated.length,
      categories: [...categories].map(([category, total_cents]) => ({ category, total_cents })),
      months: [...months.values()],
    };
    return route.fulfill({
      json: {
        total_receipts: 4,
        counts: { AUTO_FILED: 4, APPROVED: 0, REVIEW_QUEUE: 0 },
        accepted_count: dated.length,
        accepted_missing_value: 0,
        accepted_date_bounds: { first: "2018-09-10", last: "2026-10-02" },
        generated_at: "2026-10-02T00:00:00Z",
        default_currency: "SGD",
        currencies: [currency],
        reporting: {
          ...currency, available: true, source: "European Central Bank",
          as_of: "2026-10-02", stale: false,
        },
      },
    });
  });

  await page.goto("/ui/");
  await page.getByLabel("App API key").fill(key);
  await page.getByRole("button", { name: "Sign in securely" }).click();
  await expect(page.getByText("All time · 10 Sep 2018 – 2 Oct 2026").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "SGD 2534.41" })).toBeVisible();
  expect(lastDashboardQuery).toContain("dated_only=true");
  await expect(page.getByRole("button", { name: /Accepted receipts 4/ })).toBeVisible();
  await expect(page.getByText("Yearly view")).toBeVisible();

  await page.getByRole("button", { name: "Latest 3 months" }).click();
  await expect(page.getByRole("heading", { name: "SGD 2532.88" })).toBeVisible();
  await expect(page.getByText("Monthly view")).toBeVisible();
  await expect(page.getByRole("button", { name: /Accepted receipts 3/ })).toBeVisible();
  await expect(page.getByText("Travel and Transport", { exact: true })).toBeVisible();

  await page.getByLabel("Accepted expenses start date").fill("2026-09-01");
  await page.getByLabel("Accepted expenses end date").fill("2026-09-30");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(page.getByRole("heading", { name: "SGD 2432.88" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Accepted receipts 2/ })).toBeVisible();
  await expect(page.getByText("Travel and Transport", { exact: true })).toHaveCount(0);
  await page.getByText("View this date range").click();
  await expect(page.getByRole("heading", { name: "Receipt history" })).toBeVisible();
  await expect(page.getByLabel("Receipt date from")).toHaveValue("2026-09-01");
  await expect(page.getByLabel("Receipt date to")).toHaveValue("2026-09-30");
  await expect(page.getByText("1–2 of 2")).toBeVisible();
  await page.getByRole("button", { name: "Main dashboard", exact: true }).click();
  const allReceipts = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === "/receipts" && !url.searchParams.has("state")
      && !url.searchParams.has("date_from") && !url.searchParams.has("date_to");
  });
  await page.getByText("Open receipt history").click();
  await allReceipts;
  await expect(page.getByLabel("Receipt date from")).toHaveValue("");
  await expect(page.getByLabel("Receipt date to")).toHaveValue("");
  await expect(page.getByText("All statuses")).toBeVisible();
  await expect(page.getByText("1–4 of 4")).toBeVisible();
});
