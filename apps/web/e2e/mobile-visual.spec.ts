import { test, expect } from "@playwright/test";

// Runs across chromium (desktop), mobile-390 (iPhone 12), and mobile-780
// (see playwright.config.ts). Not a pixel-diff suite - it asserts the mobile
// polish contract (no horizontal scroll, key content stays visible) and
// drops a screenshot per surface/project into test-results for manual review.

async function assertNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const viewport = page.viewportSize();
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth).toBeLessThanOrEqual(viewport!.width + 1);
}

// Regression guard for the horizontal-pan bug: the empty-state chip row was
// flex-nowrap but its shrink-wrapping parent let it stretch past the
// viewport, so overflow-x-auto on the row never engaged and the messages
// scroll container panned sideways instead. Checks the document itself and
// the messages scroll container (data-testid="messages-scroll") directly.
async function assertNoDocumentOrMessagesPan(page: import("@playwright/test").Page) {
  const doc = await page.evaluate(() => ({
    scrollWidth: document.scrollingElement?.scrollWidth ?? 0,
    clientWidth: document.scrollingElement?.clientWidth ?? 0,
  }));
  expect(doc.scrollWidth).toBeLessThanOrEqual(doc.clientWidth);

  const messages = page.getByTestId("messages-scroll");
  const messagesOverflow = await messages.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(messagesOverflow.scrollWidth).toBeLessThanOrEqual(messagesOverflow.clientWidth);
}

// Guy overrode the horizontal-scroll-row chip design with a stacked one
// (each chip on its own row, full text visible). Replaces the old
// scroll-row assertion: every chip in the given testid container must sit
// fully inside the viewport - no clipped/overflowing right edge.
async function assertChipsFullyInViewport(page: import("@playwright/test").Page, testId: string) {
  const viewport = page.viewportSize()!;
  const chips = page.getByTestId(testId).getByRole("button");
  const count = await chips.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const box = await chips.nth(i).boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport.width + 1);
  }
}

test("landing: no horizontal overflow, hero and CTA visible", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Airport Investment Intelligence Agent" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start asking" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("landing.png"), fullPage: true });
});

test("chat empty state: no horizontal overflow, prompt and composer visible", async ({ page }, testInfo) => {
  await page.goto("/chat");
  await expect(page.getByText("Ask an investment question about US airports.")).toBeVisible();
  await expect(page.getByPlaceholder("Ask about an airport, a region, or a comparison...")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await assertNoDocumentOrMessagesPan(page);
  await assertChipsFullyInViewport(page, "empty-state-chips");
  await page.screenshot({ path: testInfo.outputPath("chat-empty.png"), fullPage: true });
});

test("/3d: stage loads without crashing", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  await page.goto("/3d");
  await expect(page.locator("#stage")).toBeVisible();
  await expect(page.locator("#stage canvas")).toBeVisible();
  expect(pageErrors).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("3d.png") });
});
