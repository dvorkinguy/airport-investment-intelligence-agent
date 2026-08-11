import { test, expect } from "@playwright/test";

// Exactly 3 smoke tests (rule 0) against one production build whose backend
// URL is intentionally dead - see playwright.config.ts. Tests 1-2 don't
// depend on backend connectivity, so they exercise that same server safely.

const ANALYST_QUESTIONS = [
  "Which airports in New England are strong candidates for terminal expansion?",
  "Compare congestion at LAX and SNA.",
  "What percentage of flights out of Anchorage are long-haul?",
  "What is the estimated unmet flight demand at SFO, and why?",
];

test("landing renders title, all 4 question cards, and Start asking", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Airport Investment Intelligence Agent/);
  await expect(page.getByRole("heading", { name: "Airport Investment Intelligence Agent" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Start asking" })).toBeVisible();
  for (const question of ANALYST_QUESTIONS) {
    await expect(page.getByRole("link", { name: question })).toBeVisible();
  }
});

test("/chat renders the input, send button, and mic button", async ({ page }) => {
  await page.goto("/chat");
  await expect(
    page.getByPlaceholder("Ask about an airport, a region, or a comparison..."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start voice input" })).toBeVisible();
});

test("backend-down state shows the production banner without crashing", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  await page.goto("/chat");
  await expect(page.getByText("Agent backend not connected yet.")).toBeVisible();
  // The rest of the UI must still be there - a banner, not a blank/broken page.
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();

  expect(pageErrors).toEqual([]);
});
