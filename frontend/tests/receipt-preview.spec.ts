import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

const key = "preview-test-only-app-key-32-characters";
// A real tall PNG makes receipt-size changes visible; no OCR/gateway calls.
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAHgAAAJYAQAAAACBLB9gAAAAL0lEQVR42u3HoQEAAAgDoOn/P2u2eQA0anJ03N3d3d3d3d3d3d3d3d3d3d3d3d/fMFalQFr4Y847YAAAAASUVORK5CYII=",
  "base64",
);

async function setup(page: Page, longTitle = "") {
  await page.addInitScript(() => {
    const resources = { created: [] as string[], revoked: [] as string[] };
    Reflect.set(window, "previewResources", resources);
    const create = URL.createObjectURL.bind(URL),
      revoke = URL.revokeObjectURL.bind(URL);
    URL.createObjectURL = (blob) => {
      const url = create(blob);
      resources.created.push(url);
      return url;
    };
    URL.revokeObjectURL = (url) => {
      resources.revoked.push(url);
      revoke(url);
    };
  });
  const rows = Array.from({ length: 20 }, (_, i) => ({
    receipt_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, "0")}`,
    vendor:
      i === 0 && longTitle
        ? longTitle
        : `Receipt ${String(i + 1).padStart(2, "0")}`,
    created_at: "2026-09-13T12:00:00Z",
    total_amount: i + 1,
    currency: "MYR",
    decision: "AUTO_FILED",
  }));
  await page.route("**/receipts?*", (route) =>
    route.fulfill({ json: { items: rows, total: 20, limit: 20, offset: 0 } }),
  );
  await page.route("**/dashboard", (route) =>
    route.fulfill({
      json: {
        total_receipts: 20,
        counts: { AUTO_FILED: 20 },
        currencies: [],
        accepted_missing_value: 0,
        generated_at: "2026-09-13T12:00:00Z",
      },
    }),
  );
  await page.goto("/ui/");
  await page.getByLabel("App API key").fill(key);
  await page.getByRole("button", { name: "Connect to workspace" }).click();
  await page
    .getByRole("button", { name: "Receipt history", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Preview receipt Receipt 20",
      exact: true,
    }),
  ).toBeAttached();
}

test("twelve successive slow-image previews keep their size and placement", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await setup(page);
  let gate = Promise.resolve();
  await page.route(/\/receipts\/[^/]+\/image$/, async (route) => {
    expect(route.request().headers()["x-api-key"]).toBe(key);
    await gate;
    await route.fulfill({ contentType: "image/png", body: png }).catch(() => {
      /* Opening/closing can cancel the request. */
    });
  });
  const changes: {
    receipt: number;
    before: string | null;
    after: string | null;
    heightChange: number;
  }[] = [];
  for (let i = 1; i <= 12; i++) {
    let release!: () => void;
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const name = `Receipt ${String(i).padStart(2, "0")}`;
    await page
      .getByRole("button", { name: `Preview receipt ${name}`, exact: true })
      .hover();
    const card = page.getByRole("dialog", {
      name: `Receipt preview for ${name}`,
      exact: true,
    });
    await expect(card.getByText("Loading preview…")).toBeVisible();
    // Finish entry animation before measuring the actual reserved layout.
    await card.evaluate(async (element) => {
      await Promise.all(
        element.getAnimations().map((animation) => animation.finished),
      );
    });
    const before = await card.boundingBox(),
      side = await card.getAttribute("data-side");
    release();
    const image = card.getByAltText("Quick preview of original receipt");
    await expect(image).toBeVisible();
    await expect
      .poll(() =>
        image.evaluate(
          (element) => (element as HTMLImageElement).naturalHeight,
        ),
      )
      .toBe(600);
    const after = await card.boundingBox();
    changes.push({
      receipt: i,
      before: side,
      after: await card.getAttribute("data-side"),
      heightChange: Math.round(after!.height - before!.height),
    });
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
  }
  expect(
    changes.filter(
      (change) =>
        change.before !== change.after || Math.abs(change.heightChange) > 1,
    ),
  ).toEqual([]);
  const resources = (await page.evaluate(() =>
    Reflect.get(window, "previewResources"),
  )) as { created: string[]; revoked: string[] };
  expect(resources.created.length).toBeGreaterThanOrEqual(12);
  expect(resources.revoked.sort()).toEqual(resources.created.sort());
});

test("short-screen preview never scrolls and keeps a long vendor title fixed", async ({
  page,
}) => {
  const title = "A VERY LONG VENDOR AND RECEIPT TITLE ".repeat(8).trim();
  await page.setViewportSize({ width: 375, height: 420 });
  await setup(page, title);
  await page.route(/\/receipts\/[^/]+\/image$/, (route) =>
    route.fulfill({ contentType: "image/png", body: png }),
  );
  for (const height of [420, 360]) {
    await page.setViewportSize({ width: 375, height });
    await page
      .getByRole("button", { name: `Preview receipt ${title}`, exact: true })
      .click();
    const card = page.getByRole("dialog", {
      name: `Receipt preview for ${title}`,
      exact: true,
    });
    await expect(
      card.getByAltText("Quick preview of original receipt"),
    ).toBeVisible();
    await card.evaluate(async (element) => {
      await Promise.all(
        element.getAnimations().map((animation) => animation.finished),
      );
    });
    const header = card.locator('[data-slot="preview-header"]');
    const before = await header.boundingBox();
    const layout = await card.evaluate((element) => {
      element.scrollTop = 100;
      return {
        overflow: getComputedStyle(element).overflowY,
        scrollTop: element.scrollTop,
        overflowSize: element.scrollHeight - element.clientHeight,
      };
    });
    expect(layout.overflow).toBe("hidden");
    expect(layout.scrollTop).toBe(0);
    expect(layout.overflowSize).toBeLessThanOrEqual(1);
    expect(await header.boundingBox()).toEqual(before);
    await expect(card.getByRole("heading")).toHaveAttribute("title", title);
    const box = await card.boundingBox(),
      footer = await card
        .getByRole("button", { name: "Open full receipt" })
        .boundingBox();
    expect(before!.height).toBe(48);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.y + box!.height).toBeLessThanOrEqual(height);
    expect(footer!.y + footer!.height).toBeLessThanOrEqual(
      box!.y + box!.height,
    );
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
  }
});

test("hovering a sixth receipt replaces a pinned preview without overlapping open cards", async ({
  page,
}) => {
  await setup(page);
  await page.route(/\/receipts\/[^/]+\/image$/, (route) =>
    route.fulfill({ contentType: "image/png", body: png }),
  );
  await page
    .getByRole("button", { name: "Preview receipt Receipt 01", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Close receipt preview" }),
  ).toBeFocused();
  await page
    .getByRole("button", { name: "Preview receipt Receipt 06", exact: true })
    .hover();
  const card = page.getByRole("dialog", {
    name: "Receipt preview for Receipt 06",
    exact: true,
  });
  await expect(
    card.getByAltText("Quick preview of original receipt"),
  ).toBeVisible();
  await expect(page.locator('.receipt-preview[data-state="open"]')).toHaveCount(
    1,
  );
  await expect(
    page.getByRole("dialog", {
      name: "Receipt preview for Receipt 01",
      exact: true,
    }),
  ).toHaveCount(0);
  await card.evaluate(async (element) => {
    await Promise.all(
      element.getAnimations().map((animation) => animation.finished),
    );
  });
  expect(
    await card.evaluate((element) => getComputedStyle(element).transform),
  ).toBe("none");
  await page.keyboard.press("Escape");
  await expect(card).toHaveCount(0);
});

test("closing animation retains the loaded image until the preview unmounts", async ({
  page,
}) => {
  await setup(page);
  await page.route(/\/receipts\/[^/]+\/image$/, (route) =>
    route.fulfill({ contentType: "image/png", body: png }),
  );
  await page
    .getByRole("button", { name: "Preview receipt Receipt 01", exact: true })
    .hover();
  const card = page.getByRole("dialog", {
    name: "Receipt preview for Receipt 01",
    exact: true,
  });
  await expect(
    card.getByAltText("Quick preview of original receipt"),
  ).toBeVisible();
  await card.evaluate(async (element) => {
    await Promise.all(
      element.getAnimations().map((animation) => animation.finished),
    );
  });
  const closing = await page.evaluate(() => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    return new Promise<{ state: string | null; images: number }>((resolve) =>
      requestAnimationFrame(() => {
        const preview = document.querySelector(".receipt-preview");
        resolve({
          state: preview?.getAttribute("data-state") || null,
          images: preview?.querySelectorAll("img").length || 0,
        });
      }),
    );
  });
  expect(closing).toEqual({ state: "closed", images: 1 });
  await expect(card).toHaveCount(0);
  const resources = (await page.evaluate(() =>
    Reflect.get(window, "previewResources"),
  )) as { created: string[]; revoked: string[] };
  expect(resources.revoked.sort()).toEqual(resources.created.sort());
});
